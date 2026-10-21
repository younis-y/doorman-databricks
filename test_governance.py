"""Offline governance tests. Run with python3 -m unittest -v test_governance."""

import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, call, patch
import uuid


class GovernanceTests(unittest.TestCase):
    def setUp(self):
        database = types.ModuleType("db")
        database.run_sql = Mock(return_value=[])
        self.run_sql = database.run_sql
        source = Path(__file__).with_name("governance.py")
        spec = importlib.util.spec_from_file_location("governance_under_test", source)
        self.governance = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"db": database}), patch.dict(
            os.environ, {"DATA_CATALOG": "test_catalog", "DATA_SCHEMA": "test_schema"}
        ):
            spec.loader.exec_module(self.governance)
        self.requester = "analyst@example.com"
        self.approver = "owner@example.com"
        self.table = "test_catalog.test_schema.test_asset"
        self.request_id = "request-123"
        self.row = {
            "id": self.request_id,
            "requester": self.requester,
            "approver": self.approver,
            "table_name": self.table,
            "status": "pending",
        }
        self.tags = [
            {"table_name": "test_asset", "tag_name": "data_owner", "tag_value": self.approver},
            {"table_name": "test_asset", "tag_name": "licence_cost_gbp", "tag_value": "120"},
            {"table_name": "test_asset", "tag_name": "sensitivity", "tag_value": "licensed"},
            {"table_name": "test_asset", "tag_name": "description", "tag_value": "Test asset"},
        ]

    def assert_decision(self, status, note):
        statement, parameters = self.run_sql.call_args.args
        self.assertTrue(statement.startswith("UPDATE test_catalog.test_schema.access_requests"))
        self.assertIn("decided_at = current_timestamp()", statement)
        self.assertEqual(parameters, {
            "st": status, "by": self.approver, "note": note, "id": self.request_id,
        })

    def test_catalogue_pivots_tags_and_excludes_tables_without_owner(self):
        self.run_sql.return_value = self.tags + [
            {"table_name": "untagged", "tag_name": "sensitivity", "tag_value": "internal"},
            {"table_name": "empty_owner", "tag_name": "data_owner", "tag_value": ""},
        ]
        self.assertEqual(self.governance.requestable(), {
            self.table: {
                "data_owner": self.approver,
                "licence_cost_gbp": "120",
                "sensitivity": "licensed",
                "description": "Test asset",
            },
        })
        statement, parameters = self.run_sql.call_args.args
        self.assertIn("test_catalog.information_schema.table_tags", statement)
        self.assertEqual(parameters, {"s": "test_schema"})

    def test_catalogue_can_be_empty(self):
        self.assertEqual(self.governance.requestable(), {})

    def test_submit_rejects_blank_reasons_without_sql(self):
        for reason in (None, "", " \n\t"):
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(ValueError, "a reason is required"):
                    self.governance.submit_request(self.requester, self.table, reason)
        self.run_sql.assert_not_called()

    def test_submit_rejects_invalid_requesters_without_sql(self):
        for requester in (None, "", "not-an-email", "analyst@example.com`; DROP TABLE x; --"):
            with self.subTest(requester=requester):
                with self.assertRaisesRegex(ValueError, "not an email"):
                    self.governance.submit_request(requester, self.table, "Risk reporting")
        self.run_sql.assert_not_called()

    def test_submit_rejects_non_requestable_table(self):
        self.run_sql.return_value = self.tags
        with self.assertRaisesRegex(ValueError, "not requestable"):
            self.governance.submit_request(self.requester, "unlisted.table", "Risk reporting")
        self.run_sql.assert_called_once()

    def test_submit_rejects_duplicate_pending_request(self):
        self.run_sql.side_effect = [self.tags, [{"1": "1"}]]
        with self.assertRaisesRegex(ValueError, "already have a pending request"):
            self.governance.submit_request(self.requester, self.table, "Risk reporting")
        self.assertEqual(self.run_sql.call_count, 2)
        statement, parameters = self.run_sql.call_args.args
        self.assertIn("status = 'pending'", statement)
        self.assertEqual(parameters, {"r": self.requester, "t": self.table})

    def test_submit_uses_tag_owner_cost_uuid_and_parameterized_reason(self):
        self.run_sql.side_effect = [self.tags, [], []]
        reason = "  Desk's risk report; SELECT is just text  "
        request_id = self.governance.submit_request(self.requester, self.table, reason)
        self.assertEqual(uuid.UUID(request_id).version, 4)
        statement, parameters = self.run_sql.call_args.args
        self.assertTrue(statement.startswith("INSERT INTO test_catalog.test_schema.access_requests"))
        self.assertIn("'pending'", statement)
        self.assertIn("ai_classify(:reason", statement)
        self.assertIn("current_timestamp()", statement)
        self.assertNotIn(reason.strip(), statement)
        self.assertEqual(parameters, {
            "id": request_id, "r": self.requester, "t": self.table,
            "reason": reason.strip(), "cost": "120", "appr": self.approver,
        })

    def test_submit_defaults_missing_cost_to_zero(self):
        self.run_sql.side_effect = [[self.tags[0]], [], []]
        self.governance.submit_request(self.requester, self.table, "Risk reporting")
        self.assertEqual(self.run_sql.call_args.args[1]["cost"], "0")

    def test_submit_propagates_insert_failure(self):
        self.run_sql.side_effect = [self.tags, [], RuntimeError("classification unavailable")]
        with self.assertRaisesRegex(RuntimeError, "classification unavailable"):
            self.governance.submit_request(self.requester, self.table, "Risk reporting")

    def test_approve_rejects_missing_request(self):
        with self.assertRaisesRegex(ValueError, "no request"):
            self.governance.approve(self.request_id, self.approver)
        self.run_sql.assert_called_once()
        self.assertEqual(self.run_sql.call_args.args[1], {"id": self.request_id})

    def test_approve_rejects_wrong_approver_without_grants(self):
        self.run_sql.return_value = [self.row]
        with self.assertRaises(PermissionError):
            self.governance.approve(self.request_id, "other@example.com")
        self.run_sql.assert_called_once()

    def test_approve_rejects_decided_requests_without_grants(self):
        for status in ("approved", "rejected", "failed", "revoked"):
            with self.subTest(status=status):
                self.run_sql.reset_mock()
                self.run_sql.return_value = [{**self.row, "status": status}]
                with self.assertRaisesRegex(ValueError, f"already {status}"):
                    self.governance.approve(self.request_id, self.approver)
                self.run_sql.assert_called_once()

    def test_approve_rechecks_catalogue_before_granting(self):
        self.run_sql.side_effect = [[self.row], []]
        with self.assertRaisesRegex(ValueError, "no longer requestable"):
            self.governance.approve(self.request_id, self.approver)
        self.assertEqual(self.run_sql.call_count, 2)

    def test_approve_rejects_invalid_stored_requester_without_grants(self):
        self.run_sql.side_effect = [[{**self.row, "requester": "bad`principal"}], self.tags]
        with self.assertRaisesRegex(ValueError, "not an email"):
            self.governance.approve(self.request_id, self.approver)
        self.assertEqual(self.run_sql.call_count, 2)

    def test_approve_grants_schema_then_table_before_recording_success(self):
        self.run_sql.side_effect = [[self.row], self.tags, [], [], []]
        self.governance.approve(self.request_id, self.approver, None)
        self.assertEqual(self.run_sql.call_args_list[2:4], [
            call(f"GRANT USE SCHEMA ON SCHEMA test_catalog.test_schema TO `{self.requester}`"),
            call(f"GRANT SELECT ON TABLE {self.table} TO `{self.requester}`"),
        ])
        self.assertEqual(self.run_sql.call_count, 5)
        self.assert_decision("approved", "granted SELECT")

    def test_approve_records_failure_at_either_grant_and_reraises(self):
        for successful_grants in (0, 1):
            with self.subTest(successful_grants=successful_grants):
                self.run_sql.reset_mock()
                error = RuntimeError("permission denied")
                self.run_sql.side_effect = (
                    [[self.row], self.tags] + [[]] * successful_grants + [error, []]
                )
                with self.assertRaises(RuntimeError) as raised:
                    self.governance.approve(self.request_id, self.approver)
                self.assertIs(raised.exception, error)
                self.assertEqual(self.run_sql.call_count, 4 + successful_grants)
                self.assert_decision("failed", "GRANT failed: permission denied")

    def test_approve_truncates_failure_note(self):
        self.run_sql.side_effect = [[self.row], self.tags, RuntimeError("x" * 1500), []]
        with self.assertRaises(RuntimeError):
            self.governance.approve(self.request_id, self.approver)
        self.assert_decision("failed", ("GRANT failed: " + "x" * 1500)[:1000])

    def test_reject_requires_note_without_sql(self):
        for note in (None, "", " \n\t"):
            with self.subTest(note=note):
                with self.assertRaisesRegex(ValueError, "reason for rejecting is required"):
                    self.governance.reject(self.request_id, self.approver, note)
        self.run_sql.assert_not_called()

    def test_reject_rejects_wrong_approver_without_update(self):
        self.run_sql.return_value = [self.row]
        with self.assertRaises(PermissionError):
            self.governance.reject(self.request_id, "other@example.com", "Not needed")
        self.run_sql.assert_called_once()

    def test_reject_rejects_decided_request_without_update(self):
        self.run_sql.return_value = [{**self.row, "status": "approved"}]
        with self.assertRaisesRegex(ValueError, "already approved"):
            self.governance.reject(self.request_id, self.approver, "Not needed")
        self.run_sql.assert_called_once()

    def test_reject_records_trimmed_note_and_decision(self):
        self.run_sql.side_effect = [[self.row], []]
        self.governance.reject(self.request_id, self.approver, "  No business need  ")
        self.assertEqual(self.run_sql.call_count, 2)
        self.assert_decision("rejected", "No business need")

    def test_revoke_requires_approved_request_without_changes(self):
        self.run_sql.return_value = [self.row]
        with self.assertRaisesRegex(ValueError, "only approved requests"):
            self.governance.revoke(self.request_id, self.approver)
        self.run_sql.assert_called_once()

    def test_revoke_preserves_schema_access_when_other_approvals_exist(self):
        self.run_sql.side_effect = [[{**self.row, "status": "approved"}], [], [{"1": "1"}], []]
        self.governance.revoke(self.request_id, self.approver)
        self.assertEqual(self.run_sql.call_args_list[1],
                         call(f"REVOKE SELECT ON TABLE {self.table} FROM `{self.requester}`"))
        self.assertEqual(self.run_sql.call_count, 4)
        note = self.run_sql.call_args.args[1]["note"]
        self.assertTrue(note.startswith("revoked "))
        self.assert_decision("revoked", note)

    def test_revoke_removes_schema_access_after_last_approval(self):
        self.run_sql.side_effect = [[{**self.row, "status": "approved"}], [], [], [], []]
        self.governance.revoke(self.request_id, self.approver)
        self.assertEqual(self.run_sql.call_args_list[3], call(
            f"REVOKE USE SCHEMA ON SCHEMA test_catalog.test_schema FROM `{self.requester}`"
        ))
        self.assertEqual(self.run_sql.call_count, 5)
        self.assert_decision("revoked", self.run_sql.call_args.args[1]["note"])


if __name__ == "__main__":
    unittest.main()
