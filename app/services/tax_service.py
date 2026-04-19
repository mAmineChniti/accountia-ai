"""Tunisian Tax Service - calculates taxes per Tunisian tax law."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class TunisianTaxBreakdown:
    """Detailed Tunisian tax breakdown for a period."""
    # VAT (TVA)
    vat_standard_19: Decimal  # 19% - standard rate
    vat_reduced_13: Decimal   # 13% - reduced rate (transport, tourism)
    vat_reduced_7: Decimal    # 7% - reduced rate (medical, equipment)
    vat_exempt: Decimal       # 0% - exempt
    vat_total: Decimal
    
    # Income Tax (IS - Impôt sur les Sociétés)
    taxable_income: Decimal
    corporate_tax_rate: Decimal  # Usually 15% for SMEs, 25% for others
    corporate_tax_due: Decimal
    
    # Withholding Taxes (Retenues à la source)
    withholding_tax: Decimal
    
    # Totals
    total_tax_liability: Decimal
    
    # Filing info
    filing_period: str  # "MM/YYYY"
    due_date: datetime


class TunisianTaxService:
    """
    Tunisian Tax Calculator based on Tunisian tax law.
    
    VAT (TVA) Rates:
    - 19%: Standard rate (most goods and services)
    - 13%: Reduced rate (transport, tourism services, restaurants)
    - 7%: Reduced rate (medical equipment, pharmaceutical products, educational materials)
    - 0%: Exempt (exports, essential goods)
    
    Corporate Income Tax (IS):
    - 15%: SMEs (annual revenue <= 1M TND)
    - 25%: Standard rate for larger companies
    - 35%: Banks, financial institutions
    
    Withholding Taxes:
    - 1.5%: B2B transactions
    - 3%: Professional fees
    - 5%: Commissions, royalties
    - 15%: Dividends
    """
    
    # VAT Rates per Tunisian law
    VAT_STANDARD = Decimal("0.19")      # 19%
    VAT_REDUCED_13 = Decimal("0.13")    # 13%
    VAT_REDUCED_7 = Decimal("0.07")     # 7%
    VAT_EXEMPT = Decimal("0.00")        # 0%
    
    # Corporate tax rates
    CORPORATE_SME_RATE = Decimal("0.15")     # 15% for SMEs
    CORPORATE_STANDARD_RATE = Decimal("0.25") # 25% standard
    
    def __init__(self):
        self.logger = logger.bind(service="tunisian_tax")
    
    def calculate_vat(
        self,
        invoices: List[Dict],
        product_category_map: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Decimal]:
        """
        Calculate VAT based on Tunisian rates.
        
        Since invoices don't have taxRate field, we apply standard 19% rate
        or categorize based on product names/categories.
        
        Args:
            invoices: List of invoice documents
            product_category_map: Optional mapping of productId to category
            
        Returns:
            Dict with VAT breakdown by rate
        """
        vat_19 = Decimal("0")
        vat_13 = Decimal("0")
        vat_7 = Decimal("0")
        vat_exempt = Decimal("0")
        
        for invoice in invoices:
            total = Decimal(str(invoice.get("totalAmount", 0)))
            status = invoice.get("status", "")
            
            # Only calculate VAT for non-voided, non-draft invoices
            if status in ["DRAFT", "VOIDED", "ARCHIVED"]:
                continue
            
            # Check line items for product categories
            line_items = invoice.get("lineItems", [])
            
            if line_items and product_category_map:
                # Categorize by product
                for item in line_items:
                    product_id = str(item.get("productId", ""))
                    amount = Decimal(str(item.get("amount", 0)))
                    category = product_category_map.get(product_id, "standard")
                    
                    vat_amount = self._apply_vat_rate(amount, category)
                    
                    if category == "standard":
                        vat_19 += vat_amount
                    elif category == "transport_tourism":
                        vat_13 += vat_amount
                    elif category == "medical_education":
                        vat_7 += vat_amount
                    elif category == "exempt":
                        vat_exempt += Decimal("0")
            else:
                # No categorization available - apply standard 19%
                vat_19 += total * self.VAT_STANDARD
        
        return {
            "vat_19": vat_19,
            "vat_13": vat_13,
            "vat_7": vat_7,
            "vat_exempt": vat_exempt,
            "vat_total": vat_19 + vat_13 + vat_7,
        }
    
    def _apply_vat_rate(self, amount: Decimal, category: str) -> Decimal:
        """Apply appropriate VAT rate based on category."""
        rates = {
            "standard": self.VAT_STANDARD,
            "transport_tourism": self.VAT_REDUCED_13,
            "medical_education": self.VAT_REDUCED_7,
            "exempt": self.VAT_EXEMPT,
        }
        rate = rates.get(category, self.VAT_STANDARD)
        return amount * rate
    
    def calculate_corporate_income_tax(
        self,
        taxable_income: Decimal,
        annual_revenue: Decimal,
        is_sme: bool = True,
    ) -> Decimal:
        """
        Calculate Impôt sur les Sociétés (IS).
        
        Args:
            taxable_income: Net taxable income
            annual_revenue: Annual revenue to determine SME status
            is_sme: Force SME status (revenue <= 1M TND)
            
        Returns:
            Corporate tax amount
        """
        # SME threshold: 1,000,000 TND
        SME_THRESHOLD = Decimal("1000000")
        
        if is_sme or annual_revenue <= SME_THRESHOLD:
            rate = self.CORPORATE_SME_RATE
        else:
            rate = self.CORPORATE_STANDARD_RATE
        
        return taxable_income * rate
    
    def calculate_withholding_tax(
        self,
        payment_amount: Decimal,
        payment_type: str = "b2b",
    ) -> Decimal:
        """
        Calculate withholding tax (Retenue à la source).
        
        Rates:
        - b2b: 1.5%
        - professional_fees: 3%
        - commissions: 5%
        - dividends: 15%
        """
        rates = {
            "b2b": Decimal("0.015"),
            "professional_fees": Decimal("0.03"),
            "commissions": Decimal("0.05"),
            "dividends": Decimal("0.15"),
        }
        
        rate = rates.get(payment_type, Decimal("0.015"))
        return payment_amount * rate
    
    def calculate_period_taxes(
        self,
        business_id: str,
        invoices: List[Dict],
        products: List[Dict],
        period_start: datetime,
        period_end: datetime,
    ) -> TunisianTaxBreakdown:
        """
        Calculate all Tunisian taxes for an accounting period.
        
        This is the main entry point for tax calculation.
        """
        self.logger.info(
            "calculating_tunisian_taxes",
            business_id=business_id,
            period=f"{period_start.strftime('%Y-%m')}"
        )
        
        # Build product category map if we can infer categories
        # This is a simple heuristic - could be enhanced with ML classification
        product_category_map = self._categorize_products(products)
        
        # 1. Calculate VAT
        vat_breakdown = self.calculate_vat(invoices, product_category_map)
        
        # 2. Calculate taxable income (simplified)
        # Revenue - Deductible Expenses
        taxable_revenue = sum(
            Decimal(str(inv.get("totalAmount", 0)))
            for inv in invoices
            if inv.get("status") not in ["DRAFT", "VOIDED"]
        )
        
        # Estimate deductible expenses (COGS + operating expenses)
        # This is a simplification - real implementation needs expense tracking
        estimated_cogs = Decimal("0")
        for inv in invoices:
            for item in inv.get("lineItems", []):
                # Get product cost if available
                product_id = str(item.get("productId", ""))
                product = next(
                    (p for p in products if str(p.get("_id")) == product_id),
                    None
                )
                if product:
                    cost = Decimal(str(product.get("cost", 0)))
                    qty = Decimal(str(item.get("quantity", 1)))
                    estimated_cogs += cost * qty
        
        taxable_income = taxable_revenue - estimated_cogs
        
        # Assume SME for now - could be configured per business
        is_sme = True
        annual_revenue = taxable_revenue * 12  # Rough annual estimate
        
        corporate_tax = self.calculate_corporate_income_tax(
            taxable_income,
            annual_revenue,
            is_sme,
        )
        
        # Corporate tax rate used
        corp_rate = self.CORPORATE_SME_RATE if is_sme else self.CORPORATE_STANDARD_RATE
        
        # 3. Estimate withholding tax on payments received
        # Assuming 1.5% on B2B transactions
        withholding_tax = self.calculate_withholding_tax(
            sum(Decimal(str(inv.get("amountPaid", 0))) for inv in invoices),
            "b2b"
        )
        
        # Total tax liability
        total_tax = (
            vat_breakdown["vat_total"] +
            corporate_tax +
            withholding_tax
        )
        
        # Filing period and due date
        filing_period = period_start.strftime("%m/%Y")
        # VAT due by the 28th of the following month
        due_date = datetime(
            period_end.year,
            period_end.month + 1 if period_end.month < 12 else 1,
            28
        )
        
        return TunisianTaxBreakdown(
            vat_standard_19=vat_breakdown["vat_19"],
            vat_reduced_13=vat_breakdown["vat_13"],
            vat_reduced_7=vat_breakdown["vat_7"],
            vat_exempt=vat_breakdown["vat_exempt"],
            vat_total=vat_breakdown["vat_total"],
            taxable_income=taxable_income,
            corporate_tax_rate=corp_rate,
            corporate_tax_due=corporate_tax,
            withholding_tax=withholding_tax,
            total_tax_liability=total_tax,
            filing_period=filing_period,
            due_date=due_date,
        )
    
    def _categorize_products(self, products: List[Dict]) -> Dict[str, str]:
        """
        Categorize products for VAT purposes based on name/description.
        
        This is a heuristic - real implementation would use product categories
        from the database.
        """
        category_map = {}
        
        # Keywords for categorization
        transport_keywords = ["transport", "logistics", "shipping", "delivery", "bus", "taxi"]
        tourism_keywords = ["hotel", "restaurant", "tourism", "cafe", "food", "meal"]
        medical_keywords = ["medical", "pharma", "medicine", "health", "hospital", "drug"]
        education_keywords = ["book", "education", "school", "course", "training"]
        exempt_keywords = ["export", "essential", "bread", "milk", "basic food"]
        
        for product in products:
            product_id = str(product.get("_id", ""))
            name = product.get("name", "").lower()
            desc = product.get("description", "").lower()
            combined = f"{name} {desc}"
            
            # Check keywords
            if any(kw in combined for kw in exempt_keywords):
                category_map[product_id] = "exempt"
            elif any(kw in combined for kw in medical_keywords + education_keywords):
                category_map[product_id] = "medical_education"
            elif any(kw in combined for kw in transport_keywords + tourism_keywords):
                category_map[product_id] = "transport_tourism"
            else:
                category_map[product_id] = "standard"
        
        return category_map
    
    def get_tax_calendar(self, year: int) -> List[Dict]:
        """
        Get Tunisian tax filing calendar for a year.
        
        Returns list of filing deadlines.
        """
        deadlines = []
        
        for month in range(1, 13):
            # VAT due by 28th of next month
            due_month = month + 1 if month < 12 else 1
            due_year = year if month < 12 else year + 1
            
            deadlines.append({
                "period": f"{month:02d}/{year}",
                "vat_due_date": datetime(due_year, due_month, 28),
                "description": f"VAT declaration for {month:02d}/{year}",
            })
        
        # Corporate tax annual declaration (by March 25th)
        deadlines.append({
            "period": f"FY {year}",
            "declaration_due": datetime(year + 1, 3, 25),
            "description": f"Annual corporate tax declaration for {year}",
        })
        
        return deadlines
