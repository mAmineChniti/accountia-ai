"""Core accounting engine - processes invoices and generates journal entries."""

from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import structlog
from bson import ObjectId

from app.db.mongodb import get_tenant_db
from app.db.schemas import (
    AccountingReport,
    AccountingTask,
    FinancialSummary,
    JournalEntry,
    TaxCalculation,
)
from app.services.llm_service import get_llm_service
from app.services.tax_service import TunisianTaxService

logger = structlog.get_logger()


class AccountingEngine:
    """Processes business transactions and generates accounting entries."""
    
    def __init__(self, business_id: str, database_name: str):
        self.business_id = business_id
        self.database_name = database_name
        self.tenant_db = get_tenant_db(database_name)
        self.llm = get_llm_service()
    
    async def process_period(
        self,
        task: AccountingTask,
    ) -> AccountingTask:
        """Process an accounting period for the business."""
        
        logger.info(
            "processing_accounting_period",
            business_id=self.business_id,
            period_start=task.period_start.isoformat(),
            period_end=task.period_end.isoformat(),
        )
        
        # 1. Fetch invoices for period
        invoices = await self._fetch_invoices(task.period_start, task.period_end)
        logger.info("fetched_invoices", count=len(invoices))
        
        # 2. Fetch products for cost calculations
        products = await self._fetch_products()
        product_cost_map = {str(p["_id"]): p.get("cost", 0) for p in products}
        
        # 3. Generate journal entries
        journal_entries = await self._generate_journal_entries(
            invoices, product_cost_map
        )
        task.journal_entries = journal_entries
        
        # 4. Calculate Tunisian taxes
        tax_calculations = await self._calculate_taxes(
            invoices, products, task.period_start, task.period_end
        )
        task.tax_calculations = tax_calculations

        # 4b. Create tax liability journal entries so taxes appear in the ledger
        # and financial reports. Map common tax types to payable accounts.
        tax_entries = []
        for calc in tax_calculations:
            try:
                amt = Decimal(str(calc.tax_amount))
            except Exception:
                amt = Decimal("0")

            if amt <= 0:
                continue

            acct_name = None
            ttype = calc.tax_type.lower()
            if "vat" in ttype or "tva" in ttype:
                acct_name = "VAT Payable"
            elif "withhold" in ttype or "reten" in ttype:
                acct_name = "Withholding Tax Payable"
            elif "corporate" in ttype or "is (" in ttype or "income" in ttype:
                acct_name = "Corporate Tax Payable"
            else:
                acct_name = f"{calc.tax_type} Payable"

            tax_entries.append(JournalEntry(
                date=task.period_end or datetime.utcnow(),
                account=acct_name,
                debit=Decimal("0"),
                credit=amt,
                description=f"Tax liability: {calc.tax_type} - {calc.notes}",
            ))

        # Append tax entries to the journal entries list so they're persisted
        if tax_entries:
            if not isinstance(task.journal_entries, list):
                task.journal_entries = []
            task.journal_entries.extend(tax_entries)
        
        # 5. Generate financial summary
        task.financial_summary = self._calculate_financial_summary(
            invoices, journal_entries
        )
        
        # 6. Generate reports
        task.reports = await self._generate_reports(
            invoices, journal_entries, task.period_start, task.period_end
        )
        
        # 7. AI analysis and insights
        ai_result = await self._generate_ai_analysis(
            invoices, journal_entries, task.financial_summary
        )
        task.ai_insights = ai_result["insights"]
        task.recommendations = ai_result["recommendations"]
        task.anomalies_detected = ai_result["anomalies"]
        
        # 8. Mark as completed
        task.status = "completed"
        task.progress_percent = 100
        task.completed_at = datetime.utcnow()
        
        logger.info(
            "accounting_period_completed",
            business_id=self.business_id,
            journal_entries=len(journal_entries),
            tax_calculations=len(tax_calculations),
        )
        
        return task
    
    async def _fetch_invoices(
        self,
        start: datetime,
        end: datetime,
    ) -> List[Dict]:
        """Fetch invoices for the period."""
        cursor = self.tenant_db["invoices"].find({
            "issuerBusinessId": {"$in": [ObjectId(self.business_id), self.business_id]},
            "issuedDate": {"$gte": start, "$lte": end},
        })
        raw = await cursor.to_list(length=None)

        # Normalize invoice documents to a predictable shape so downstream
        # processing doesn't depend on varying field names or BSON types.
        normalized = [self._normalize_invoice(inv) for inv in raw]
        return normalized
    
    async def _fetch_products(self) -> List[Dict]:
        """Fetch products for the business."""
        cursor = self.tenant_db["products"].find({
            "businessId": {"$in": [ObjectId(self.business_id), self.business_id]},
        })
        raw = await cursor.to_list(length=None)
        # Convert ObjectIds to strings and ensure cost exists
        for p in raw:
            if "_id" in p:
                p["_id"] = str(p["_id"])
            if "cost" not in p:
                p["cost"] = 0
        return raw

    def _normalize_invoice(self, inv: Dict) -> Dict:
        """Normalize invoice fields to canonical names used by the engine.

        - Prefer `totalAmount` but fall back to `total` or `total_amount`.
        - Prefer `lineItems` but fall back to `lines`.
        - Ensure numeric fields are plain Python numbers (ints/floats).
        - Convert ObjectId fields to strings where convenient.
        """
        # copy shallowly to avoid mutating original
        invoice = dict(inv)

        # Normalize issuedDate exists
        issued = invoice.get("issuedDate")
        if issued is None:
            invoice["issuedDate"] = invoice.get("createdAt")

        # Normalize total field
        if "totalAmount" in invoice and invoice.get("totalAmount") is not None:
            invoice["totalAmount"] = invoice.get("totalAmount")
        elif "total" in invoice and invoice.get("total") is not None:
            invoice["totalAmount"] = invoice.get("total")
        elif "total_amount" in invoice and invoice.get("total_amount") is not None:
            invoice["totalAmount"] = invoice.get("total_amount")
        else:
            invoice.setdefault("totalAmount", 0)

        # Normalize line items
        if "lineItems" in invoice and invoice.get("lineItems") is not None:
            invoice["lineItems"] = invoice.get("lineItems")
        elif "lines" in invoice and invoice.get("lines") is not None:
            invoice["lineItems"] = invoice.get("lines")
        else:
            invoice.setdefault("lineItems", [])

        # Normalize numeric and id types
        try:
            # convert totals to plain Decimal-friendly strings/nums
            if invoice.get("totalAmount") is None:
                invoice["totalAmount"] = 0
        except Exception:
            invoice["totalAmount"] = 0

        # Convert ObjectId fields to strings for safer logging/keys
        if "_id" in invoice:
            try:
                invoice["_id"] = str(invoice["_id"])
            except Exception:
                pass
        if "issuerBusinessId" in invoice:
            try:
                invoice["issuerBusinessId"] = str(invoice["issuerBusinessId"])
            except Exception:
                pass

        return invoice
    
    async def _generate_journal_entries(
        self,
        invoices: List[Dict],
        product_cost_map: Dict[str, float],
    ) -> List[JournalEntry]:
        """Generate journal entries from invoices."""
        
        entries = []
        
        for invoice in invoices:
            inv_id = str(invoice.get("_id", ""))
            inv_date = invoice.get("issuedDate", datetime.utcnow())
            inv_number = invoice.get("invoiceNumber", "UNKNOWN")
            status = invoice.get("status", "")
            total_amount = Decimal(str(invoice.get("totalAmount", 0)))
            amount_paid = Decimal(str(invoice.get("amountPaid", 0)))
            tax_amount = Decimal(str(invoice.get("taxAmount", 0)))
            
            line_items = invoice.get("lineItems", [])
            
            # Calculate COGS from line items
            total_cogs = Decimal("0")
            for line in line_items:
                product_id = str(line.get("productId", ""))
                quantity = line.get("quantity", 0)
                unit_cost = Decimal(str(product_cost_map.get(product_id, 0)))
                total_cogs += unit_cost * Decimal(quantity)
            
            # Skip draft invoices - no revenue recognized until issued
            if status == "DRAFT":
                continue
            
            # Revenue recognition based on payment status
            if status == "PAID":
                # Full revenue recognized
                # Debit: Cash/Bank, Credit: Revenue
                entries.append(JournalEntry(
                    date=inv_date,
                    account="Cash/Bank",
                    debit=total_amount,
                    credit=Decimal("0"),
                    description=f"Payment received for invoice {inv_number}",
                    invoice_id=inv_id,
                ))
                entries.append(JournalEntry(
                    date=inv_date,
                    account="Revenue",
                    debit=Decimal("0"),
                    credit=total_amount,
                    description=f"Revenue from invoice {inv_number}",
                    invoice_id=inv_id,
                ))
                
                # COGS entry for paid invoices
                if total_cogs > 0:
                    entries.append(JournalEntry(
                        date=inv_date,
                        account="Cost of Goods Sold",
                        debit=total_cogs,
                        credit=Decimal("0"),
                        description=f"COGS for invoice {inv_number}",
                        invoice_id=inv_id,
                    ))
                    entries.append(JournalEntry(
                        date=inv_date,
                        account="Inventory",
                        debit=Decimal("0"),
                        credit=total_cogs,
                        description=f"Inventory reduction for invoice {inv_number}",
                        invoice_id=inv_id,
                    ))
                    
            elif status == "PARTIAL":
                # Partial payment
                # Debit: Cash (paid amount), Debit: Accounts Receivable (remaining)
                # Credit: Revenue (full amount)
                remaining = total_amount - amount_paid
                
                entries.append(JournalEntry(
                    date=inv_date,
                    account="Cash/Bank",
                    debit=amount_paid,
                    credit=Decimal("0"),
                    description=f"Partial payment for invoice {inv_number}",
                    invoice_id=inv_id,
                ))
                entries.append(JournalEntry(
                    date=inv_date,
                    account="Accounts Receivable",
                    debit=remaining,
                    credit=Decimal("0"),
                    description=f"Outstanding amount for invoice {inv_number}",
                    invoice_id=inv_id,
                ))
                entries.append(JournalEntry(
                    date=inv_date,
                    account="Revenue",
                    debit=Decimal("0"),
                    credit=total_amount,
                    description=f"Revenue from invoice {inv_number}",
                    invoice_id=inv_id,
                ))
                
            elif status in ["ISSUED", "VIEWED", "OVERDUE", "DISPUTED"]:
                # Revenue recognized on accrual basis
                entries.append(JournalEntry(
                    date=inv_date,
                    account="Accounts Receivable",
                    debit=total_amount,
                    credit=Decimal("0"),
                    description=f"Invoice {inv_number} issued",
                    invoice_id=inv_id,
                ))
                entries.append(JournalEntry(
                    date=inv_date,
                    account="Revenue",
                    debit=Decimal("0"),
                    credit=total_amount,
                    description=f"Revenue from invoice {inv_number}",
                    invoice_id=inv_id,
                ))
            
            # Tax entry - disabled until API adds taxRate/taxAmount fields
            # When tax fields are available, calculate and record tax liability
            pass
        
        return entries
    
    async def _calculate_taxes(
        self,
        invoices: List[Dict],
        products: List[Dict],
        period_start: datetime,
        period_end: datetime,
    ) -> List[TaxCalculation]:
        """Calculate Tunisian tax liabilities for the period."""
        
        tax_service = TunisianTaxService()
        
        tax_breakdown = tax_service.calculate_period_taxes(
            self.business_id,
            invoices,
            products,
            period_start,
            period_end,
        )
        
        calculations = []
        
        # VAT - 19% standard rate
        if tax_breakdown.vat_standard_19 > 0:
            calculations.append(TaxCalculation(
                tax_type="TVA (VAT) - Standard Rate",
                jurisdiction="Tunisia",
                taxable_amount=tax_breakdown.vat_standard_19 / tax_service.VAT_STANDARD,
                tax_rate=tax_service.VAT_STANDARD,
                tax_amount=tax_breakdown.vat_standard_19,
                notes=f"Standard VAT rate (19%) for period {tax_breakdown.filing_period}",
            ))
        
        # VAT - 13% reduced rate
        if tax_breakdown.vat_reduced_13 > 0:
            calculations.append(TaxCalculation(
                tax_type="TVA (VAT) - Reduced Rate 13%",
                jurisdiction="Tunisia",
                taxable_amount=tax_breakdown.vat_reduced_13 / tax_service.VAT_REDUCED_13,
                tax_rate=tax_service.VAT_REDUCED_13,
                tax_amount=tax_breakdown.vat_reduced_13,
                notes="Reduced rate for transport, tourism services",
            ))
        
        # VAT - 7% reduced rate
        if tax_breakdown.vat_reduced_7 > 0:
            calculations.append(TaxCalculation(
                tax_type="TVA (VAT) - Reduced Rate 7%",
                jurisdiction="Tunisia",
                taxable_amount=tax_breakdown.vat_reduced_7 / tax_service.VAT_REDUCED_7,
                tax_rate=tax_service.VAT_REDUCED_7,
                tax_amount=tax_breakdown.vat_reduced_7,
                notes="Reduced rate for medical, education",
            ))
        
        # Corporate Income Tax (IS)
        if tax_breakdown.corporate_tax_due > 0:
            calculations.append(TaxCalculation(
                tax_type="IS (Corporate Income Tax)",
                jurisdiction="Tunisia",
                taxable_amount=tax_breakdown.taxable_income,
                tax_rate=tax_breakdown.corporate_tax_rate,
                tax_amount=tax_breakdown.corporate_tax_due,
                notes=f"Rate: {tax_breakdown.corporate_tax_rate * 100}%",
            ))
        
        # Withholding Tax
        if tax_breakdown.withholding_tax > 0:
            calculations.append(TaxCalculation(
                tax_type="Withholding Tax",
                jurisdiction="Tunisia",
                taxable_amount=tax_breakdown.withholding_tax / Decimal("0.015"),
                tax_rate=Decimal("0.015"),
                tax_amount=tax_breakdown.withholding_tax,
                notes="Retenue à la source on B2B transactions (1.5%)",
            ))
        
        logger.info(
            "tunisian_taxes_calculated",
            business_id=self.business_id,
            vat_total=float(tax_breakdown.vat_total),
            corporate_tax=float(tax_breakdown.corporate_tax_due),
            total=float(tax_breakdown.total_tax_liability),
        )
        
        return calculations
    
    def _calculate_financial_summary(
        self,
        invoices: List[Dict],
        journal_entries: List[JournalEntry],
    ) -> FinancialSummary:
        """Calculate key financial metrics."""
        
        total_revenue = Decimal("0")
        total_expenses = Decimal("0")
        ar_balance = Decimal("0")
        ap_balance = Decimal("0")
        
        for entry in journal_entries:
            if entry.account == "Revenue" and entry.credit > 0:
                total_revenue += entry.credit
            elif entry.account == "Cost of Goods Sold" and entry.debit > 0:
                total_expenses += entry.debit
            elif entry.account == "Accounts Receivable" and entry.debit > 0:
                ar_balance += entry.debit
            elif entry.account == "Accounts Receivable" and entry.credit > 0:
                ar_balance -= entry.credit
        
        gross_profit = total_revenue - total_expenses
        
        # Calculate cash position from paid invoices
        cash_position = Decimal("0")
        for inv in invoices:
            if inv.get("status") == "PAID":
                cash_position += Decimal(str(inv.get("totalAmount", 0)))
        
        return FinancialSummary(
            total_revenue=total_revenue,
            total_expenses=total_expenses,
            gross_profit=gross_profit,
            net_profit=gross_profit,  # Simplified - would subtract operating expenses
            accounts_receivable=ar_balance,
            accounts_payable=ap_balance,
            cash_position=cash_position,
        )
    
    async def _generate_reports(
        self,
        invoices: List[Dict],
        journal_entries: List[JournalEntry],
        start: datetime,
        end: datetime,
    ) -> List[AccountingReport]:
        """Generate standard accounting reports."""
        
        reports = []
        
        # P&L Report
        pl_data = self._generate_pl_data(invoices, journal_entries)
        reports.append(AccountingReport(
            report_type="P&L",
            period_start=start,
            period_end=end,
            data=pl_data,
        ))
        
        # Balance Sheet (simplified)
        bs_data = self._generate_balance_sheet_data(journal_entries)
        reports.append(AccountingReport(
            report_type="Balance Sheet",
            period_start=start,
            period_end=end,
            data=bs_data,
        ))
        
        # General Ledger
        gl_data = self._generate_ledger_data(journal_entries)
        reports.append(AccountingReport(
            report_type="General Ledger",
            period_start=start,
            period_end=end,
            data=gl_data,
        ))
        
        return reports
    
    def _generate_pl_data(
        self,
        invoices: List[Dict],
        journal_entries: List[JournalEntry],
    ) -> Dict:
        """Generate P&L data."""
        revenue = Decimal("0")
        cogs = Decimal("0")
        
        for entry in journal_entries:
            if entry.account == "Revenue":
                revenue += entry.credit
            elif entry.account == "Cost of Goods Sold":
                cogs += entry.debit
        
        return {
            "revenue": float(revenue),
            "cost_of_goods_sold": float(cogs),
            "gross_profit": float(revenue - cogs),
            "gross_margin_pct": float((revenue - cogs) / revenue * 100) if revenue > 0 else 0,
        }
    
    def _generate_balance_sheet_data(
        self,
        journal_entries: List[JournalEntry],
    ) -> Dict:
        """Generate simplified balance sheet."""
        accounts: Dict[str, Decimal] = {}
        
        for entry in journal_entries:
            if entry.account not in accounts:
                accounts[entry.account] = Decimal("0")
            accounts[entry.account] += entry.debit - entry.credit
        
        return {k: float(v) for k, v in accounts.items()}
    
    def _generate_ledger_data(
        self,
        journal_entries: List[JournalEntry],
    ) -> Dict:
        """Generate general ledger entries by account."""
        ledger: Dict[str, List] = {}
        
        for entry in journal_entries:
            if entry.account not in ledger:
                ledger[entry.account] = []
            ledger[entry.account].append({
                "date": entry.date.isoformat(),
                "description": entry.description,
                "debit": float(entry.debit),
                "credit": float(entry.credit),
                "invoice_id": entry.invoice_id,
            })
        
        return ledger
    
    async def _generate_ai_analysis(
        self,
        invoices: List[Dict],
        journal_entries: List[JournalEntry],
        summary: FinancialSummary,
    ) -> Dict:
        """Use LLM to generate insights and detect anomalies."""
        
        # Prepare summary for LLM
        invoice_summary = {
            "total_invoices": len(invoices),
            "paid_count": sum(1 for i in invoices if i.get("status") == "PAID"),
            "outstanding_count": sum(1 for i in invoices if i.get("status") in ["SENT", "OVERDUE"]),
            "total_revenue": float(summary.total_revenue),
            "gross_profit": float(summary.gross_profit),
        }
        
        prompt = f"""Analyze this business's accounting data for the period:

Financial Summary:
{invoice_summary}

Journal Entries Summary:
- Total entries: {len(journal_entries)}
- Revenue recognized: {sum(float(e.credit) for e in journal_entries if e.account == 'Revenue')}
- COGS: {sum(float(e.debit) for e in journal_entries if e.account == 'Cost of Goods Sold')}
- Accounts Receivable: {float(summary.accounts_receivable)}
- Cash Position: {float(summary.cash_position)}

Provide:
1. Key insights about the financial performance
2. 3-5 actionable recommendations
3. Any anomalies or red flags detected

Respond in JSON format with keys: insights (string), recommendations (array of strings), anomalies (array of objects with 'description' and 'severity')."""
        
        schema = {
            "insights": "string - 2-3 paragraph analysis",
            "recommendations": ["string - actionable advice"],
            "anomalies": [{"description": "string", "severity": "low|medium|high"}],
        }
        
        system_prompt = """You are an expert accountant analyzing business financials. 
Provide professional, accurate accounting analysis. Be concise but thorough."""
        
        try:
            result = await self.llm.generate_structured(
                prompt=prompt,
                output_schema=schema,
                system_prompt=system_prompt,
            )
            return {
                "insights": result.get("insights", ""),
                "recommendations": result.get("recommendations", []),
                "anomalies": result.get("anomalies", []),
            }
        except Exception as e:
            logger.error("ai_analysis_failed", error=str(e))
            return {
                "insights": "AI analysis unavailable. Please review financial summary manually.",
                "recommendations": [],
                "anomalies": [],
            }
