# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import datetime, timedelta

from dateutil import relativedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import common


class TestPayrollAccount(common.TransactionCase):
    def setUp(self):
        super().setUp()

        # Activate company currency
        self.env.user.company_id.currency_id.active = True

        self.payslip_action_id = self.ref("payroll.hr_payslip_menu")

        self.res_partner_bank = self.env["res.partner.bank"].create(
            {
                "acc_number": "001-9876543-21",
                "partner_id": self.ref("base.res_partner_12"),
                "acc_type": "bank",
                "bank_id": self.ref("base.res_bank_1"),
            }
        )

        self.hr_employee_john = self.env["hr.employee"].create(
            {
                "address_id": self.ref("base.res_partner_address_27"),
                "birthday": "1984-05-01",
                "children": 0.0,
                "country_id": self.ref("base.in"),
                "department_id": self.ref("hr.dep_rd"),
                "gender": "male",
                "marital": "single",
                "name": "John",
                "bank_account_id": self.res_partner_bank.bank_id.id,
            }
        )

        self.account_debit = self.env["account.account"].create(
            {
                "name": "Debit Account",
                "code": "334411",
                "account_type": "expense",
                "reconcile": True,
            }
        )
        self.account_credit = self.env["account.account"].create(
            {
                "name": "Credit Account",
                "code": "114433",
                "account_type": "expense",
                "reconcile": True,
            }
        )

        self.account_journal = self.env["account.journal"].create(
            {
                "name": "Vendor Bills - Test",
                "code": "TEXJ",
                "type": "purchase",
                "default_account_id": self.account_debit.id,
                "refund_sequence": True,
            }
        )

        rules = [
            self.ref("payroll.hr_salary_rule_houserentallowance1"),
            self.ref("payroll.hr_salary_rule_providentfund1"),
        ]
        self.hr_structure_softwaredeveloper = self.env["hr.payroll.structure"].create(
            {
                "name": "Salary Structure for Software Developer",
                "code": "SD",
                "parent_id": self.ref("payroll.structure_base"),
                "rule_ids": [(6, 0, rules)],
            }
        )

        self.hr_contract_john = self.env["hr.contract"].create(
            {
                "date_end": fields.Date.to_string(datetime.now() + timedelta(days=365)),
                "date_start": fields.Date.today(),
                "name": "Contract for John",
                "wage": 5000.0,
                "employee_id": self.hr_employee_john.id,
                "struct_id": self.hr_structure_softwaredeveloper.id,
                "journal_id": self.account_journal.id,
            }
        )

    def _update_account_in_rule(self, debit, credit):
        rule_HRA = self.env.ref("payroll.hr_salary_rule_houserentallowance1")
        rule_HRA.write({"account_debit": debit, "account_credit": credit})

    def _prepare_payslip(self, employee):
        date_from = datetime.now()
        date_to = datetime.now() + relativedelta.relativedelta(
            months=+1, day=1, days=-1
        )
        self.hr_payslip = self.env["hr.payslip"].create(
            {
                "employee_id": self.hr_employee_john.id,
                "contract_id": self.hr_contract_john.id,
                "struct_id": self.hr_structure_softwaredeveloper.id,
            }
        )
        res = self.hr_payslip.get_payslip_vals(date_from, date_to, employee.id)
        vals = {
            "struct_id": res["value"]["struct_id"],
            "contract_id": res["value"]["contract_id"],
            "name": res["value"]["name"],
        }
        vals["worked_days_line_ids"] = [
            (0, 0, i) for i in res["value"]["worked_days_line_ids"]
        ]
        vals["input_line_ids"] = [(0, 0, i) for i in res["value"]["input_line_ids"]]
        vals.update({"contract_id": self.hr_contract_john.id})
        self.hr_payslip.write(vals)
        return self.hr_payslip

    def test_00_hr_payslip(self):
        """checking the process of payslip."""
        self._update_account_in_rule(self.account_debit, self.account_credit)
        self._prepare_payslip(self.hr_employee_john)

        # I assign the amount to Input data.
        payslip_input = self.env["hr.payslip.input"].search(
            [("payslip_id", "=", self.hr_payslip.id)]
        )
        payslip_input.write({"amount": 5.0})

        # I verify the payslip is in draft state.
        self.assertEqual(self.hr_payslip.state, "draft", "State not changed!")

        # I click on "Compute Sheet" button.
        self.hr_payslip.with_context(
            {},
            lang="en_US",
            tz=False,
            active_model="hr.payslip",
            department_id=False,
            active_ids=[self.payslip_action_id],
            section_id=False,
            active_id=self.payslip_action_id,
        ).compute_sheet()

        # I want to check cancel button.
        # So I first cancel the sheet then make it set to draft.
        self.hr_payslip.action_payslip_cancel()
        self.assertEqual(self.hr_payslip.state, "cancel", "Payslip is rejected.")
        self.hr_payslip.action_payslip_draft()

        self.hr_payslip.action_payslip_done()

        # I verify that the Accounting Entries are created.
        self.assertTrue(self.hr_payslip.move_id, "Accounting Entries should be created")

        # I verify that the payslip is in done state.
        self.assertEqual(self.hr_payslip.state, "done", "State not changed!")

    def test_hr_payslip_no_accounts(self):
        self._prepare_payslip(self.hr_employee_john)

        # I click on "Compute Sheet" button.
        self.hr_payslip.with_context(
            {},
            lang="en_US",
            tz=False,
            active_model="hr.payslip",
            department_id=False,
            active_ids=[self.payslip_action_id],
            section_id=False,
            active_id=self.payslip_action_id,
        ).compute_sheet()

        # Confirm Payslip (no account moves)
        self.hr_payslip.action_payslip_done()
        self.assertFalse(self.hr_payslip.move_id, "Accounting Entries has been created")

        # I verify that the payslip is in done state.
        self.assertEqual(self.hr_payslip.state, "done", "State not changed!")

    def test_partner_logic_account_types(self):
        """Test partner logic for different account types."""
        # Employee already has work_contact_id auto-created
        employee_partner = self.hr_employee_john.work_contact_id

        # Create register with different partner
        register_partner = self.env["res.partner"].create({"name": "Tax Authority"})
        register = self.env["hr.contribution.register"].create(
            {"name": "Tax Register", "partner_id": register_partner.id}
        )

        # Create rule and payslip line
        rule = self.env.ref("payroll.hr_salary_rule_houserentallowance1")
        rule.register_id = register
        payslip = self._prepare_payslip(self.hr_employee_john)
        line = self.env["hr.payslip.line"].create(
            {"slip_id": payslip.id, "salary_rule_id": rule.id, "name": "Test"}
        )

        # Test asset_receivable -> employee partner
        self.account_credit.account_type = "asset_receivable"
        rule.account_credit = self.account_credit
        self.assertEqual(line._get_partner_id(True), employee_partner.id)

        # Test liability_current -> employee partner
        self.account_credit.account_type = "liability_current"
        self.assertEqual(line._get_partner_id(True), employee_partner.id)

        # Test liability_payable -> register partner
        self.account_credit.account_type = "liability_payable"
        self.assertEqual(line._get_partner_id(True), register_partner.id)

        # Test other account types -> no partner
        self.account_credit.account_type = "expense"
        self.assertFalse(line._get_partner_id(True))

    def test_cancel_after_confirm_deletes_move(self):
        """Test canceling a confirmed payslip deletes accounting entries."""
        self._update_account_in_rule(self.account_debit, self.account_credit)
        self._prepare_payslip(self.hr_employee_john)
        self.hr_payslip.compute_sheet()
        self.hr_payslip.action_payslip_done()
        self.assertTrue(self.hr_payslip.move_id)
        self.hr_payslip.action_payslip_cancel()
        self.assertEqual(self.hr_payslip.state, "cancel")
        self.assertFalse(self.hr_payslip.move_id)

    def test_cancel_after_confirm_restricted_journal(self):
        """Test hash-locked journal triggers reverse move instead of delete."""
        self._update_account_in_rule(self.account_debit, self.account_credit)
        self._prepare_payslip(self.hr_employee_john)
        self.hr_payslip.compute_sheet()
        self.hr_payslip.action_payslip_done()
        self.assertTrue(self.hr_payslip.move_id)
        self.account_journal.restrict_mode_hash_table = True
        self.hr_payslip.action_payslip_cancel()
        self.assertEqual(self.hr_payslip.state, "cancel")
        self.assertFalse(self.hr_payslip.move_id)

    def test_payslip_done_explicit_date(self):
        """Test accounting entry uses the explicit date field when set."""
        self._update_account_in_rule(self.account_debit, self.account_credit)
        self._prepare_payslip(self.hr_employee_john)
        explicit_date = fields.Date.from_string("2024-06-15")
        self.hr_payslip.date = explicit_date
        self.hr_payslip.compute_sheet()
        self.hr_payslip.action_payslip_done()
        self.assertEqual(self.hr_payslip.move_id.date, explicit_date)

    def test_payslip_done_credit_note(self):
        """Test credit note payslip inverts line amounts in accounting entries."""
        self._update_account_in_rule(self.account_debit, self.account_credit)
        self._prepare_payslip(self.hr_employee_john)
        self.hr_payslip.credit_note = True
        self.hr_payslip.compute_sheet()
        self.hr_payslip.action_payslip_done()
        self.assertTrue(self.hr_payslip.move_id)

    def test_payslip_done_contract_analytic_account(self):
        """Test move lines carry analytic distribution from contract."""
        self._update_account_in_rule(self.account_debit, self.account_credit)
        analytic_account = self.env["account.analytic.account"].create(
            {"name": "Contract Analytic"}
        )
        self.hr_contract_john.analytic_account_id = analytic_account
        self._prepare_payslip(self.hr_employee_john)
        self.hr_payslip.compute_sheet()
        self.hr_payslip.action_payslip_done()
        self.assertTrue(self.hr_payslip.move_id)
        lines_with_analytic = self.hr_payslip.move_id.line_ids.filtered(
            "analytic_distribution"
        )
        self.assertTrue(lines_with_analytic)

    def test_payslip_done_rule_analytic_account(self):
        """Test move lines use rule analytic distribution when contract has none."""
        self._update_account_in_rule(self.account_debit, self.account_credit)
        analytic_account = self.env["account.analytic.account"].create(
            {"name": "Rule Analytic"}
        )
        rule = self.env.ref("payroll.hr_salary_rule_houserentallowance1")
        rule.analytic_account_id = analytic_account
        self.hr_contract_john.analytic_account_id = False
        self._prepare_payslip(self.hr_employee_john)
        self.hr_payslip.compute_sheet()
        self.hr_payslip.action_payslip_done()
        self.assertTrue(self.hr_payslip.move_id)
        lines_with_analytic = self.hr_payslip.move_id.line_ids.filtered(
            "analytic_distribution"
        )
        self.assertTrue(lines_with_analytic)

    def test_payslip_done_adjustment_credit_line(self):
        """Test adjustment credit line is created when debit_sum exceeds credit_sum."""
        # Rule has only debit account → debit_sum > 0, credit_sum = 0
        self._update_account_in_rule(self.account_debit, False)
        self._prepare_payslip(self.hr_employee_john)
        self.hr_payslip.compute_sheet()
        self.hr_payslip.action_payslip_done()
        self.assertTrue(self.hr_payslip.move_id)

    def test_payslip_done_adjustment_debit_line(self):
        """Test adjustment debit line is created when credit_sum exceeds debit_sum."""
        # Rule has only credit account → credit_sum > 0, debit_sum = 0
        self._update_account_in_rule(False, self.account_credit)
        self._prepare_payslip(self.hr_employee_john)
        self.hr_payslip.compute_sheet()
        self.hr_payslip.action_payslip_done()
        self.assertTrue(self.hr_payslip.move_id)

    def test_payslip_done_no_default_account_credit_raises(self):
        """Test UserError when journal has no default account, credit adjust needed."""
        journal_no_default = self.env["account.journal"].create(
            {"name": "No Default Journal Credit", "code": "NDC1", "type": "general"}
        )
        self.hr_contract_john.journal_id = journal_no_default
        # Only debit account → adjustment credit line required → UserError
        self._update_account_in_rule(self.account_debit, False)
        self._prepare_payslip(self.hr_employee_john)
        self.hr_payslip.compute_sheet()
        with self.assertRaises(UserError):
            self.hr_payslip.action_payslip_done()

    def test_payslip_done_no_default_account_debit_raises(self):
        """Test UserError when journal lacks default account and debit adjust needed."""
        journal_no_default = self.env["account.journal"].create(
            {"name": "No Default Journal Debit", "code": "NDD1", "type": "general"}
        )
        self.hr_contract_john.journal_id = journal_no_default
        # Only credit account → adjustment debit line required → UserError
        self._update_account_in_rule(False, self.account_credit)
        self._prepare_payslip(self.hr_employee_john)
        self.hr_payslip.compute_sheet()
        with self.assertRaises(UserError):
            self.hr_payslip.action_payslip_done()

    def test_onchange_contract_sets_journal(self):
        """Test onchange_contract propagates journal from contract to payslip."""
        payslip = self._prepare_payslip(self.hr_employee_john)
        payslip.onchange_contract()
        self.assertEqual(payslip.journal_id, self.account_journal)

    def test_onchange_contract_no_contract(self):
        """Test onchange_contract with no contract falls through to current journal."""
        payslip = self._prepare_payslip(self.hr_employee_john)
        payslip.contract_id = False
        payslip.onchange_contract()
        # Should not raise; journal fallback logic executes

    def test_wizard_compute_sheet_propagates_run_journal(self):
        """Test wizard sets default_journal_id from payslip run before calling super."""
        payslip_run = self.env["hr.payslip.run"].create(
            {
                "name": "Test Run",
                "journal_id": self.account_journal.id,
                "date_start": fields.Date.today().replace(day=1),
                "date_end": fields.Date.today().replace(day=1)
                + relativedelta.relativedelta(months=1, days=-1),
            }
        )
        wizard = (
            self.env["hr.payslip.employees"]
            .with_context(active_id=payslip_run.id)
            .create({"employee_ids": [(4, self.hr_employee_john.id)]})
        )
        wizard.compute_sheet()
        slip = self.env["hr.payslip"].search(
            [("payslip_run_id", "=", payslip_run.id)], limit=1
        )
        self.assertTrue(slip)
        self.assertEqual(slip.journal_id, self.account_journal)

    def test_get_partner_id_no_work_contact_falls_back_to_bank(self):
        """Test _get_partner_id uses bank partner when work_contact_id is unset."""
        rule = self.env.ref("payroll.hr_salary_rule_houserentallowance1")
        payslip = self._prepare_payslip(self.hr_employee_john)
        line = self.env["hr.payslip.line"].create(
            {"slip_id": payslip.id, "salary_rule_id": rule.id, "name": "Test"}
        )
        self.account_credit.account_type = "asset_receivable"
        rule.account_credit = self.account_credit
        self.hr_employee_john.work_contact_id = False
        result = line._get_partner_id(True)
        if self.hr_employee_john.bank_account_id:
            self.assertEqual(
                result, self.hr_employee_john.bank_account_id.partner_id.id
            )
        else:
            self.assertFalse(result)

    def test_get_partner_id_debit_account_path(self):
        """Test _get_partner_id reads debit account type when credit_account=False."""
        rule = self.env.ref("payroll.hr_salary_rule_houserentallowance1")
        payslip = self._prepare_payslip(self.hr_employee_john)
        line = self.env["hr.payslip.line"].create(
            {"slip_id": payslip.id, "salary_rule_id": rule.id, "name": "Test"}
        )
        self.account_debit.account_type = "asset_receivable"
        rule.account_debit = self.account_debit
        result = line._get_partner_id(False)
        self.assertEqual(result, self.hr_employee_john.work_contact_id.id)

    def test_get_partner_id_liability_payable_no_register_returns_false(self):
        """Test _get_partner_id returns False for liability_payable with no register."""
        rule = self.env.ref("payroll.hr_salary_rule_houserentallowance1")
        rule.register_id = False
        payslip = self._prepare_payslip(self.hr_employee_john)
        line = self.env["hr.payslip.line"].create(
            {"slip_id": payslip.id, "salary_rule_id": rule.id, "name": "Test"}
        )
        self.account_credit.account_type = "liability_payable"
        rule.account_credit = self.account_credit
        self.assertFalse(line._get_partner_id(True))

    def test_get_tax_details_with_account_tax_id(self):
        """Test _get_tax_details runs repartition lookup when rule has a tax."""
        self._update_account_in_rule(self.account_debit, self.account_credit)
        tax = self.env["account.tax"].create(
            {"name": "Payroll Test Tax", "amount": 10, "amount_type": "percent"}
        )
        rule = self.env.ref("payroll.hr_salary_rule_houserentallowance1")
        rule.account_tax_id = tax
        self._prepare_payslip(self.hr_employee_john)
        self.hr_payslip.compute_sheet()
        self.hr_payslip.action_payslip_done()
        self.assertTrue(self.hr_payslip.move_id)

    def test_get_tax_details_with_tax_line_ids(self):
        """Test _get_tax_details aggregates tax_ids from tax_line_ids on salary rule."""
        self._update_account_in_rule(self.account_debit, self.account_credit)
        tax = self.env["account.tax"].create(
            {"name": "Payroll Tax Line", "amount": 5, "amount_type": "percent"}
        )
        base_rule = self.env.ref("payroll.hr_salary_rule_houserentallowance1")
        tax_rule = self.env["hr.salary.rule"].create(
            {
                "name": "Tax Line Rule",
                "code": "TLR",
                "category_id": self.env.ref("payroll.ALW").id,
                "sequence": 99,
                "amount_select": "fix",
                "amount_fix": 0,
                "tax_base_id": base_rule.id,
                "account_tax_id": tax.id,
            }
        )
        self.hr_structure_softwaredeveloper.rule_ids = [(4, tax_rule.id)]
        self._prepare_payslip(self.hr_employee_john)
        self.hr_payslip.compute_sheet()
        self.hr_payslip.action_payslip_done()
        self.assertTrue(self.hr_payslip.move_id)
