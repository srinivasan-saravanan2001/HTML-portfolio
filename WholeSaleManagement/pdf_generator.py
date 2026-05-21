import urllib.request
import json
from io import BytesIO
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Image as RLImage
from typing import List, Dict, Any, Optional

colors_primary    = "#b43880"
colors_secondary  = "#ad3c7a"
colors_light_bg   = "#f8fafc"
colors_border     = "#d0d7de"
colors_text_dark  = "#1e293b"
colors_text_light = "#64748b"
colors_white      = "#ffffff"
colors_warning_bg = "#fff7ed"  
colors_warning_fg = "#c2410c"   
colors_charge_bg  = "#f0fdf4"  
colors_charge_fg  = "#166534"   
colors_remark_bg  = "#eff6ff"   
colors_remark_fg  = "#1e40af"  


def get_pdf_styles():
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name='OrdCompanyName', parent=styles['Heading1'],
        fontSize=20, textColor=colors.HexColor(colors_primary),
        alignment=0, spaceAfter=0, spaceBefore=0,
        fontName='Helvetica-Bold', leading=18,
    ))
    styles.add(ParagraphStyle(
        name='OrdSubHeader', parent=styles['Normal'],
        fontSize=8, textColor=colors.HexColor(colors_text_light),
        alignment=0, spaceAfter=0, spaceBefore=0,
        fontName='Helvetica', leading=8,
    ))
    styles.add(ParagraphStyle(
        name='OrdTableHeader', parent=styles['Normal'],
        fontSize=7, textColor=colors.HexColor(colors_white),
        alignment=1, fontName='Helvetica-Bold', leading=9,
    ))
    styles.add(ParagraphStyle(
        name='OrdTableCell', parent=styles['Normal'],
        fontSize=7, textColor=colors.HexColor(colors_text_dark),
        fontName='Helvetica', leading=9, alignment=0,
    ))
    styles.add(ParagraphStyle(
        name='OrdTableCellCenter', parent=styles['Normal'],
        fontSize=7, textColor=colors.HexColor(colors_text_dark),
        fontName='Helvetica', leading=9, alignment=1,
    ))
    styles.add(ParagraphStyle(
        name='OrdTableCellRight', parent=styles['Normal'],
        fontSize=7, textColor=colors.HexColor(colors_text_dark),
        fontName='Helvetica', leading=9, alignment=2,
    ))
    styles.add(ParagraphStyle(
        name='OrdFooterNote', parent=styles['Normal'],
        fontSize=7, textColor=colors.HexColor(colors_text_light),
        fontName='Helvetica', leading=10,
    ))
    styles.add(ParagraphStyle(
        name='OrdLargeOrderId', parent=styles['Normal'],
        fontSize=16, textColor=colors.HexColor(colors_primary),
        alignment=1, spaceAfter=2, spaceBefore=0,
        fontName='Helvetica-Bold', leading=18,
    ))
    styles.add(ParagraphStyle(
        name='OrdSectionHeader', parent=styles['Heading3'],
        fontSize=10, textColor=colors.HexColor(colors_primary),
        spaceBefore=2, spaceAfter=0,
        fontName='Helvetica-Bold', leading=12,
    ))

    styles.add(ParagraphStyle(
        name='InvCompanyName', parent=styles['Heading1'],
        fontSize=20, textColor=colors.HexColor(colors_primary),
        alignment=0, spaceAfter=0, spaceBefore=0,
        fontName='Helvetica-Bold', leading=12,
    ))
    styles.add(ParagraphStyle(
        name='InvSubHeader', parent=styles['Normal'],
        fontSize=8, textColor=colors.HexColor(colors_text_light),
        alignment=0, spaceAfter=0, spaceBefore=0,
        fontName='Helvetica', leading=8,
    ))
    styles.add(ParagraphStyle(
        name='InvDocTitle', parent=styles['Heading2'],
        fontSize=14, textColor=colors.HexColor(colors_secondary),
        alignment=1, spaceAfter=8, spaceBefore=8,
        fontName='Helvetica-Bold', leading=16,
    ))
    styles.add(ParagraphStyle(
        name='InvInfoLabel', parent=styles['Normal'],
        fontSize=7, textColor=colors.HexColor(colors_text_light),
        fontName='Helvetica', leading=9,
    ))
    styles.add(ParagraphStyle(
        name='InvInfoValue', parent=styles['Normal'],
        fontSize=8, textColor=colors.HexColor(colors_text_dark),
        fontName='Helvetica-Bold', leading=10,
    ))
    styles.add(ParagraphStyle(
        name='InvInfoValueSmall', parent=styles['Normal'],
        fontSize=7, textColor=colors.HexColor(colors_text_dark),
        fontName='Helvetica', leading=9,
    ))
    styles.add(ParagraphStyle(
        name='InvTableHeader', parent=styles['Normal'],
        fontSize=7, textColor=colors.HexColor(colors_white),
        alignment=1, fontName='Helvetica-Bold', leading=9, wordWrap='CJK',
    ))
    styles.add(ParagraphStyle(
        name='InvTableCell', parent=styles['Normal'],
        fontSize=7, textColor=colors.HexColor(colors_text_dark),
        fontName='Helvetica', leading=9, wordWrap='CJK', alignment=0,
    ))
    styles.add(ParagraphStyle(
        name='InvTableCellRight', parent=styles['Normal'],
        fontSize=7, textColor=colors.HexColor(colors_text_dark),
        fontName='Helvetica', leading=9, wordWrap='CJK', alignment=2,
    ))
    styles.add(ParagraphStyle(
        name='InvTableCellCenter', parent=styles['Normal'],
        fontSize=7, textColor=colors.HexColor(colors_text_dark),
        fontName='Helvetica', leading=9, wordWrap='CJK', alignment=1,
    ))
    styles.add(ParagraphStyle(
        name='InvGroupHeader', parent=styles['Normal'],
        fontSize=8, textColor=colors.HexColor(colors_primary),
        fontName='Helvetica-Bold', leading=10, alignment=1,
    ))
    styles.add(ParagraphStyle(
        name='InvStatusText', parent=styles['Normal'],
        fontSize=8, textColor=colors.HexColor(colors_text_dark),
        alignment=1, fontName='Helvetica-Bold', leading=10,
    ))
    styles.add(ParagraphStyle(
        name='InvChargeLabel', parent=styles['Normal'],
        fontSize=7, textColor=colors.HexColor(colors_charge_fg),
        fontName='Helvetica-Bold', leading=9, alignment=2,  
    ))
    styles.add(ParagraphStyle(
        name='InvChargeValue', parent=styles['Normal'],
        fontSize=7, textColor=colors.HexColor(colors_charge_fg),
        fontName='Helvetica-Bold', leading=9, alignment=2,   
    ))
    styles.add(ParagraphStyle(
        name='InvRemarkText', parent=styles['Normal'],
        fontSize=7, textColor=colors.HexColor(colors_remark_fg),
        fontName='Helvetica', leading=9, alignment=0,      
    ))
    styles.add(ParagraphStyle(
        name='TotalLabel', parent=styles['Normal'],
        fontSize=9, textColor=colors.HexColor(colors_text_dark),
        fontName='Helvetica', leading=11, alignment=2,
    ))
    styles.add(ParagraphStyle(
        name='TotalValue', parent=styles['Normal'],
        fontSize=9, textColor=colors.HexColor(colors_text_dark),
        fontName='Helvetica', leading=11, alignment=2,
    ))
    styles.add(ParagraphStyle(
        name='TotalLabelBold', parent=styles['Normal'],
        fontSize=11, textColor=colors.HexColor(colors_primary),
        fontName='Helvetica-Bold', leading=13, alignment=2,
    ))
    styles.add(ParagraphStyle(
        name='TotalValueBold', parent=styles['Normal'],
        fontSize=11, textColor=colors.HexColor(colors_primary),
        fontName='Helvetica-Bold', leading=13, alignment=2,
    ))
    styles.add(ParagraphStyle(
        name='OutstandingLabel', parent=styles['Normal'],
        fontSize=9, textColor=colors.HexColor(colors_warning_fg),
        fontName='Helvetica-Bold', leading=11, alignment=2,
    ))
    styles.add(ParagraphStyle(
        name='OutstandingValue', parent=styles['Normal'],
        fontSize=9, textColor=colors.HexColor(colors_warning_fg),
        fontName='Helvetica-Bold', leading=11, alignment=2,
    ))

    styles.add(ParagraphStyle(
        name='CompanyName', parent=styles['Heading1'],
        fontSize=16, textColor=colors.HexColor(colors_primary),
        alignment=0, spaceAfter=2, fontName='Helvetica-Bold',
    ))
    styles.add(ParagraphStyle(
        name='CompanySub', parent=styles['Normal'],
        fontSize=9, alignment=0, spaceAfter=1, textColor=colors.grey,
    ))

    return styles



async def get_company_details() -> dict:
    url = "https://yenerp.com/purchaseapi/pobusiness/"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            if response.status == 200:
                data = json.loads(response.read().decode())
                if data and len(data) > 0:
                    company = data[0]
                    return {
                        "name":      company.get("companyName", "N/A"),
                        "address1":  company.get("address1", ""),
                        "address2":  company.get("address2", ""),
                        "phone":     company.get("phoneNo", ""),
                        "gst":       company.get("gstIn", ""),
                        "logo_url":  company.get("imageUrl", None),
                    }
    except Exception as e:
        print(f"Warning: Failed to fetch company details: {e}")
    return {"name": "Company", "address1": "", "address2": "", "phone": "", "gst": "", "logo_url": None}


def _safe_text(value, default: str = "N/A") -> str:
    return str(value) if value is not None else default

def _fmt_date(date_value) -> str:
    if not date_value:
        return "N/A"
    try:
        if isinstance(date_value, str):
            date_value = datetime.fromisoformat(date_value)
        return date_value.strftime("%d-%m-%Y")
    except Exception:
        return str(date_value)

def _load_logo(logo_url: Optional[str], width: int = 50, height: int = 50) -> Optional[RLImage]:
    """Fetch a remote logo and return an RLImage, or None on failure."""
    if not logo_url or logo_url.startswith("blob:"):
        return None
    try:
        with urllib.request.urlopen(logo_url, timeout=5) as resp:
            img = RLImage(BytesIO(resp.read()), width=width, height=height)
            img.hAlign = "LEFT"
            return img
    except Exception as e:
        print(f"Could not load logo: {e}")
        return None

def _separator_line(available_width: float) -> Table:
    """Thin primary-colour separator line."""
    line = Table([[""]], colWidths=[available_width])
    line.setStyle(TableStyle([
        ("LINEABOVE",    (0, 0), (-1, 0), 2, colors.HexColor(colors_primary)),
        ("TOPPADDING",   (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
    ]))
    return line

def _build_outstanding_row(
    previous_outstanding: float,
    spacer_w: float,
    LABEL_W: float,
    VALUE_W: float,
    styles,
) -> Optional[Table]:

    if previous_outstanding <= 0:
        return None

    row = Table(
        [[
            "",
            Paragraph("TOTAL OUTSTANDING:", styles["OutstandingLabel"]),
            Paragraph(f"Rs. {previous_outstanding:.2f}", styles["OutstandingValue"]),
        ]],
        colWidths=[spacer_w, LABEL_W, VALUE_W],
    )
    row.setStyle(TableStyle([
        ("BACKGROUND",    (1, 0), (2, 0), colors.HexColor(colors_warning_bg)),
        ("BOX",           (1, 0), (2, 0), 1, colors.HexColor(colors_warning_fg)),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
    ]))
    return row


def _item_display_name(item: dict, styles) -> Paragraph:
    variance_name = _safe_text(item.get("varianceName"), "")
    item_name     = item.get("itemName") or ""

    if item_name:
        text = (
            f'<font size="5" color="{colors_text_light}"><b>{item_name}</b></font>'
            f'<br/>'
            f'<font size="7" color="{colors_text_dark}">{variance_name}</font>'
        )
    else:
        text = f'<font size="7" color="{colors_text_dark}">{variance_name}</font>'

    return Paragraph(text, styles["OrdTableCell"])



def build_order_pdf(
    item: dict,
    company_info: dict,
    previous_outstanding: float = 0.0,
) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=25, leftMargin=25, topMargin=25, bottomMargin=25,
    )
    styles = get_pdf_styles()
    story = []
    available_width = A4[0] - doc.leftMargin - doc.rightMargin
    ci = company_info or {}

    logo_img = _load_logo(ci.get("logo_url"))
    full_address = ", ".join(
        [p for p in [ci.get("address1", "").strip(), ci.get("address2", "").strip()] if p]
    )

    details_table = Table(
        [
            [Paragraph(f"<b>{ci.get('name', 'Company Name')}</b>", styles["CompanyName"])],
            [Paragraph(full_address, styles["CompanySub"])],
            [Paragraph(f"GSTIN: {ci.get('gst', 'N/A')} | Phone: {ci.get('phone', 'N/A')}", styles["CompanySub"])],
        ],
        colWidths=[available_width - 60],
    )

    if logo_img:
        header_table = Table([[logo_img, details_table]], colWidths=[60, available_width - 60])
    else:
        header_table = Table([[details_table]], colWidths=[available_width])

    story.append(header_table)

    line = Table([[""]], colWidths=[available_width])
    line.setStyle(TableStyle([
        ("LINEABOVE",     (0, 0), (-1, 0), 2, colors.HexColor(colors_primary)),
        ("TOPPADDING",    (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(line)
    story.append(Spacer(1, 0.02 * inch))


    story.append(Paragraph("ORDER CONFIRMATION", styles["InvDocTitle"]))
    story.append(Spacer(1, 0.1 * inch))
    order_id = item.get("orderId", item.get("id", "N/A"))
    info_data = [
        [
            Paragraph("ORDER ID",   styles["InvInfoLabel"]),
            Paragraph(order_id,     styles["InvInfoValue"]),
            Paragraph("ORDER DATE", styles["InvInfoLabel"]),
            Paragraph(_fmt_date(item.get("createdDate")), styles["InvInfoValue"]),
        ],
        [
            Paragraph("COMPANY NAME", styles["InvInfoLabel"]),
            Paragraph(_safe_text(item.get("companyName")), styles["InvInfoValue"]),
            Paragraph("CONTACT",      styles["InvInfoLabel"]),
            Paragraph(_safe_text(item.get("phoneNumber")), styles["InvInfoValue"]),
        ],
        [
            Paragraph("DELIVERY DATE", styles["InvInfoLabel"]),
            Paragraph(_fmt_date(item.get("deliveryDate")), styles["InvInfoValue"]),
            Paragraph("", styles["InvInfoLabel"]),
            Paragraph("", styles["InvInfoValue"]),
        ],
        [
            Paragraph("ADDRESS",  styles["InvInfoLabel"]),
            Paragraph(_safe_text(item.get("address")), styles["InvInfoValueSmall"]),
            Paragraph("", styles["InvInfoLabel"]),
            Paragraph("", styles["InvInfoValue"]),
        ],
    ]
    info_table = Table(info_data, colWidths=[85, 185, 90, 185])
    info_table.setStyle(TableStyle([
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("BOX",          (0, 0), (-1, -1), 0.5, colors.HexColor(colors_border)),
        ("BACKGROUND",   (0, 0), (-1, -1), colors.HexColor(colors_light_bg)),
        ("LINEBELOW",    (0, 0), (-1, -2), 0.5, colors.HexColor(colors_border)),
        ("LEFTPADDING",  (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING",   (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 0.15 * inch))
    LABEL_W = 110
    VALUE_W = 105
    TOTAL_W = LABEL_W + VALUE_W
    spacer_w = available_width - TOTAL_W

    outstanding_row = _build_outstanding_row(
        previous_outstanding, spacer_w, LABEL_W, VALUE_W, styles
    )
    if outstanding_row:
        story.append(outstanding_row)
        story.append(Spacer(1, 0.15 * inch))
    col_widths = [30, 250, 50, 40, 40, 35, 40, 50]

    items_data = [[
        Paragraph(h, styles["InvTableHeader"])
        for h in ["S.No", "ITEM NAME", "QTY", "UOM", "PRICE", "DISC %", "DISC VAL", "TOTAL"]
    ]]

    for i, si in enumerate(item.get("items", [])):


        qty_val = si.get("quantityKg")

        qty_str = "0"
        if qty_val is not None and qty_val > 0:
            kg_part = int(qty_val)
            gm_decimal = qty_val - kg_part
            gm_part = round(gm_decimal * 1000)
            qty_str = f"{kg_part} Kg {gm_part} Gm"
        else:
            qty_str = str(si.get("quantity", 0))

        price = si.get("variance_Defaultprice", 0)
        line_total = si.get("lineTotal", 0)

        disc_pct = si.get("discountPercentage", 0) or 0
        disc_val = si.get("discountValue", 0) or 0

        rows_data = [
            Paragraph(str(i + 1), styles["OrdTableCellCenter"]),
            _item_display_name(si, styles),  
            Paragraph(qty_str, styles["OrdTableCellCenter"]),
            Paragraph(_safe_text(si.get("variance_Uom"), "-"), styles["OrdTableCellCenter"]),
            Paragraph(f"{price:.2f}", styles["OrdTableCellRight"]),
            Paragraph(f"{disc_pct:.1f}%", styles["OrdTableCellCenter"]),
            Paragraph(f"{disc_val:.2f}", styles["OrdTableCellRight"]),
            Paragraph(f"{line_total:.2f}", styles["OrdTableCellRight"]),
        ]
        items_data.append(rows_data)

    items_table = Table(items_data, colWidths=col_widths, repeatRows=1)
    items_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor(colors_primary)),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.HexColor(colors_white)),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0),  7),
        ("ALIGN",         (0, 0), (-1, 0),  "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("GRID",          (0, 0), (-1, -1), 0.5, colors.HexColor(colors_border)),
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 1), (-1, -1), 7),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.HexColor(colors_white), colors.HexColor("#fafafa")]),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ALIGN",         (0, 1), (0, -1),  "CENTER"),
        ("ALIGN",         (1, 1), (1, -1),  "LEFT"),
        ("ALIGN",         (2, 1), (2, -1),  "CENTER"),
        ("ALIGN",         (3, 1), (3, -1),  "CENTER"),
        ("ALIGN",         (4, 1), (4, -1),  "RIGHT"),
        ("ALIGN",         (5, 1), (5, -1),  "CENTER"),
        ("ALIGN",         (6, 1), (6, -1),  "RIGHT"),
        ("ALIGN",         (7, 1), (7, -1),  "RIGHT"),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 0.1 * inch))
    total_amount    = item.get("totalAmount", 0)
    gross_amount    = item.get("grossAmount", 0)
    discount_amount = item.get("discountAmount", 0)

    charge_amount = item.get("chargeAmount", 0) or 0

    totals_rows = []
    style_cmds = [
        ("FONTNAME",      (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE",       (0, 0), (-1, -1), 9),
        ("ALIGN",          (1, 0), (2, -1),  "RIGHT"),
        ("ALIGN",          (2, 0), (2, -1),  "RIGHT"),
        ("TOPPADDING",     (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 3),
        ("LEFTPADDING",    (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 4),
    ]

    row_idx = 0
    if gross_amount > 0:
        totals_rows.append([
            "",
            Paragraph("GROSS TOTAL:", styles["TotalLabel"]),
            Paragraph(f"Rs. {gross_amount:.2f}", styles["TotalValue"]),
        ])
        row_idx += 1

    if discount_amount > 0:
        totals_rows.append([
            "",
            Paragraph("DISCOUNT:", styles["TotalLabel"]),
            Paragraph(f"- Rs. {discount_amount:.2f}", styles["TotalValue"]),
        ])
        row_idx += 1

    if charge_amount > 0:
        totals_rows.append([
            "",
            Paragraph("CUSTOM CHARGE:", styles["TotalLabel"]),
            Paragraph(f"+ Rs. {charge_amount:.2f}", styles["TotalValue"]),
        ])
        row_idx += 1

    grand_row_idx = row_idx
    totals_rows.append([
        "",
        Paragraph("GRAND TOTAL:", styles["TotalLabelBold"]),
        Paragraph(f"Rs. {total_amount:.2f}", styles["TotalValueBold"]),
    ])

    style_cmds.extend([
        ("LINEABOVE",   (1, grand_row_idx), (2, grand_row_idx), 1.5, colors.HexColor(colors_primary)),
    ])

    grand_total_table = Table(
        totals_rows,
        colWidths=[spacer_w, LABEL_W, VALUE_W],
    )
    grand_total_table.setStyle(TableStyle(style_cmds))
    story.append(grand_total_table)
    story.append(Spacer(1, 0.15 * inch))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes



def _build_invoice_pdf(
    items: list,
    invoice_no: str,
    company_info: dict,
    paid_amount: Optional[float] = None,
    pending_amount: Optional[float] = None,
    amount_status: Optional[str] = None,
    previous_outstanding: float = 0.0,
) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=25, leftMargin=25, topMargin=25, bottomMargin=25)
    styles = get_pdf_styles()
    story  = []
    available_width = A4[0] - doc.leftMargin - doc.rightMargin
    ci = company_info or {}
    logo_img = _load_logo(ci.get("logo_url"))
    full_address = ", ".join(
        [p for p in [ci.get("address1", "").strip(), ci.get("address2", "").strip()] if p]
    )

    details_table = Table(
        [
            [Paragraph(f"<b>{ci.get('name', 'Company Name')}</b>", styles["CompanyName"])],
            [Paragraph(full_address, styles["CompanySub"])],
            [Paragraph(f"GSTIN: {ci.get('gst', 'N/A')} | Phone: {ci.get('phone', 'N/A')}", styles["CompanySub"])],
        ],
        colWidths=[available_width - 60],
    )

    if logo_img:
        header_table = Table([[logo_img, details_table]], colWidths=[60, available_width - 60])
    else:
        header_table = Table([[details_table]], colWidths=[available_width])

    story.append(header_table)
    line = Table([[""]], colWidths=[available_width])
    line.setStyle(TableStyle([
        ("LINEABOVE",     (0, 0), (-1, 0), 2, colors.HexColor(colors_primary)),
        ("TOPPADDING",    (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(line)
    story.append(Spacer(1, 0.02 * inch))
    if amount_status:
        status_label = {"fully": "FULLY PAID", "partial": "PARTIALLY PAID", "pending": "PENDING"}.get(amount_status, amount_status.upper())
        title_data = [[Paragraph("INVOICE", styles["InvDocTitle"]), Paragraph(f"({status_label})", styles["InvStatusText"])]]
        title_table = Table(title_data, colWidths=[available_width - 120, 120])
        title_table.setStyle(TableStyle([("ALIGN",  (0, 0), (0, 0), "CENTER"), ("ALIGN",  (1, 0), (1, 0), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        story.append(title_table)
    else:
        story.append(Paragraph("INVOICE", styles["InvDocTitle"]))
    story.append(Spacer(1, 0.1 * inch))
    first_item = items[0]
    info_data = [
        [Paragraph("INVOICE NO", styles["InvInfoLabel"]), Paragraph(invoice_no, styles["InvInfoValue"]), Paragraph("INVOICE DATE", styles["InvInfoLabel"]), Paragraph(datetime.now().strftime("%d-%m-%Y"), styles["InvInfoValue"])],
        [Paragraph("COMPANY NAME", styles["InvInfoLabel"]), Paragraph(_safe_text(first_item.get("companyName")), styles["InvInfoValue"]), Paragraph("CONTACT", styles["InvInfoLabel"]), Paragraph(_safe_text(first_item.get("phoneNumber")), styles["InvInfoValue"])],
        [Paragraph("ADDRESS", styles["InvInfoLabel"]), Paragraph(_safe_text(first_item.get("address")), styles["InvInfoValueSmall"])],
    ]
    info_table = Table(info_data, colWidths=[85, 185, 90, 185])
    info_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(colors_border)),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(colors_light_bg)), ("LINEBELOW", (0, 0), (-1, -2), 0.5, colors.HexColor(colors_border)),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 0.15 * inch))
    LABEL_W = 110
    VALUE_W = 105
    TOTAL_W = LABEL_W + VALUE_W
    spacer_w = available_width - TOTAL_W

    outstanding_row = _build_outstanding_row(
        previous_outstanding, spacer_w, LABEL_W, VALUE_W, styles
    )
    if outstanding_row:
        story.append(outstanding_row)
        story.append(Spacer(1, 0.15 * inch))

    col_widths = [60,     50,    155,    28,    28,    45,     35,      42,       34,    68]

    items_data = [[
        Paragraph(h, styles["InvTableHeader"])
        for h in ["ORDER ID", "DATE", "ITEM", "QTY", "UOM", "PRICE", "DISC %", "DISC VAL", "TAX", "TOTAL"]
    ]]

    special_rows: List[tuple] = []
    tax_summary: Dict[float, Dict[str, float]] = {}
    sum_gross = 0.0
    sum_discount_amount = 0.0
    sum_total_amount = 0.0
    sum_charge_amount = 0.0

    EMPTY = Paragraph("", styles["InvTableCell"])

    for inv in items:
        order_id   = inv.get("orderId", "N/A")
        inv_date   = _fmt_date(inv.get("createdDate"))
        order_gross          = inv.get("grossAmount", 0) or 0
        order_discount_amount = inv.get("discountAmount", 0) or 0
        order_total_amount   = inv.get("totalAmount", 0) or 0
        order_charge_amount  = inv.get("chargeAmount", 0) or 0

        if order_gross == 0:
            for itm in inv.get("items", []):
                order_gross += itm.get("lineTotal", 0)

        sum_gross            += order_gross
        sum_discount_amount  += order_discount_amount
        sum_total_amount     += order_total_amount
        sum_charge_amount    += order_charge_amount
        for i, sel_item in enumerate(inv.get("items", [])):
            tax_rate   = sel_item.get("tax", 0)
            qty_val = sel_item.get("quantityKg")
            if qty_val is not None and qty_val > 0:
                kg_part  = int(qty_val)
                gm_part  = round((qty_val - kg_part) * 1000)
                qty_display = f"{kg_part} Kg {gm_part} Gm"
            else:
                qty_display = str(sel_item.get("quantity", 0))

            price      = sel_item.get("variance_Defaultprice", 0)
            line_total = sel_item.get("lineTotal", 0)
            disc_pct   = sel_item.get("discountPercentage", 0) or 0
            disc_val   = sel_item.get("discountValue", 0) or 0

            if tax_rate > 0:
                tax_amt = round(line_total * (tax_rate / 100), 2)
                cgst    = round(tax_amt / 2, 2)
                sgst    = round(tax_amt / 2, 2)
                if tax_rate not in tax_summary:
                    tax_summary[tax_rate] = {"cgst": 0.0, "sgst": 0.0}
                tax_summary[tax_rate]["cgst"] += cgst
                tax_summary[tax_rate]["sgst"] += sgst

            tax_str = f"{int(tax_rate)}%" if tax_rate == int(tax_rate) else f"{tax_rate}%"

            row_vals = [
                Paragraph(order_id,                 styles["InvGroupHeader"]),
                Paragraph(inv_date,                 styles["InvTableCellCenter"]),
                _item_display_name(sel_item, styles),   
                Paragraph(qty_display,              styles["InvTableCellCenter"]),
                Paragraph(_safe_text(sel_item.get("variance_Uom"), "-"), styles["InvTableCellCenter"]),
                Paragraph(f"{price:.2f}",           styles["InvTableCellRight"]),
                Paragraph(f"{disc_pct:.1f}%",       styles["InvTableCellCenter"]),
                Paragraph(f"{disc_val:.2f}",        styles["InvTableCellRight"]),
                Paragraph(tax_str,                  styles["InvTableCellCenter"]),
                Paragraph(f"{line_total:.2f}",      styles["InvTableCellRight"]),
            ]

            if i == 0:
                items_data.append(row_vals)
            else:
                # subsequent items in same order: blank ORDER ID & DATE cols
                items_data.append(
                    [EMPTY, EMPTY] + row_vals[2:]
                )


        if order_charge_amount > 0:
            charge_row_idx = len(items_data)
            special_rows.append(("charge", charge_row_idx))
            items_data.append([
                EMPTY, EMPTY, EMPTY, EMPTY, EMPTY, EMPTY, EMPTY,
                Paragraph("CUSTOM CHARGE:", styles["InvChargeLabel"]),
                EMPTY,
                Paragraph(f"+ Rs. {order_charge_amount:.2f}", styles["InvChargeValue"]),
            ])

        if inv is not items[-1]: 
            sep_row_idx = len(items_data)
            special_rows.append(("order_sep", sep_row_idx))
            items_data.append([EMPTY] * 10)

    base_style = [
        ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor(colors_primary)),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.HexColor(colors_white)),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0),  7),
        ("ALIGN",         (0, 0), (-1, 0),  "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("GRID",          (0, 0), (-1, -1), 0.5, colors.HexColor(colors_border)),
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 1), (-1, -1), 7),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.HexColor(colors_white), colors.HexColor("#fafafa")]),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]


    for row_type, ridx in special_rows:
        if row_type == "charge":

            base_style += [
                ("SPAN",          (7, ridx), (8, ridx)),
                ("LINEABOVE",     (7, ridx), (9, ridx), 0.5, colors.HexColor(colors_charge_fg)),
                ("FONTNAME",      (7, ridx), (9, ridx), "Helvetica-Bold"),
                ("ALIGN",         (7, ridx), (9, ridx), "RIGHT"),
                ("NOSPLIT",       (0, ridx), (-1, ridx)),
                ("LINEBELOW",     (0, ridx), (6, ridx), 0,   colors.white),
                ("LINEABOVE",     (0, ridx), (6, ridx), 0,   colors.white),
            ]
        elif row_type == "order_sep":
            base_style += [
                ("SPAN",          (0, ridx), (-1, ridx)),
                ("LINEABOVE",     (0, ridx), (-1, ridx), 1.5, colors.HexColor(colors_primary)),
                ("BACKGROUND",    (0, ridx), (-1, ridx), colors.HexColor(colors_light_bg)),
                ("TOPPADDING",    (0, ridx), (-1, ridx), 1),
                ("BOTTOMPADDING", (0, ridx), (-1, ridx), 1),
            ]

    items_table = Table(items_data, colWidths=col_widths, repeatRows=1)
    items_table.setStyle(TableStyle(base_style))
    story.append(items_table)
    story.append(Spacer(1, 0.1 * inch))
    if tax_summary:
        tax_data = []
        for rate in sorted(tax_summary.keys()):
            tax_data.append(["", "", "", "", "", "", "", "", f"CGST ({rate / 2:.1f}%):", f"Rs. {tax_summary[rate]['cgst']:.2f}"])
            tax_data.append(["", "", "", "", "", "", "", "", f"SGST ({rate / 2:.1f}%):", f"Rs. {tax_summary[rate]['sgst']:.2f}"])
        tax_table = Table(tax_data, colWidths=col_widths)
        tax_table.setStyle(TableStyle([("ALIGN", (8, 0), (9, -1), "RIGHT"), ("FONTSIZE", (0, 0), (-1, -1), 8)]))
        story.append(tax_table)
        story.append(Spacer(1, 0.05 * inch))
    eff_paid    = paid_amount    if paid_amount    is not None else sum_total_amount
    eff_pending = pending_amount if pending_amount is not None else 0.0
    total_discount = sum_discount_amount if sum_discount_amount > 0 else 0.0

    totals_rows = [
        ["", "", "", "", "", "", "", "", "GROSS TOTAL:",    f"Rs. {sum_gross:.2f}"],
        ["", "", "", "", "", "", "", "", "DISCOUNT:",       f"- Rs. {total_discount:.2f}"],
    ]
    grand_row_idx = 2
    if sum_charge_amount > 0:
        totals_rows.append(
            ["", "", "", "", "", "", "", "", "CUSTOM CHARGES:", f"+ Rs. {sum_charge_amount:.2f}"]
        )
        grand_row_idx += 1

    totals_rows.append(
        ["", "", "", "", "", "", "", "", "GRAND TOTAL:",    f"Rs. {sum_total_amount:.2f}"]
    )

    if paid_amount is not None:
        totals_rows.append(["", "", "", "", "", "", "", "", "PAID AMOUNT:",    f"Rs. {eff_paid:.2f}"])
        totals_rows.append(["", "", "", "", "", "", "", "", "PENDING AMOUNT:", f"Rs. {eff_pending:.2f}"])

    style_cmds = [
        ("FONTNAME",   (0, 0),             (-1, -1),             "Helvetica"),
        ("FONTSIZE",   (0, 0),             (-1, -1),             9),
        ("ALIGN",      (8, 0),             (9, -1),              "RIGHT"),
        ("TOPPADDING", (0, 0),             (-1, -1),             3),
        ("BOTTOMPADDING", (0, 0),          (-1, -1),             3),
        ("LINEABOVE",  (8, 0),             (9, 0),               0.5, colors.HexColor(colors_border)),
        *([
            ("TEXTCOLOR",  (8, 2), (9, 2), colors.HexColor(colors_charge_fg)),
            ("FONTNAME",   (8, 2), (9, 2), "Helvetica-Bold"),
        ] if sum_charge_amount > 0 else []),
        ("LINEABOVE",  (8, grand_row_idx), (9, grand_row_idx),   1.5, colors.HexColor(colors_primary)),
        ("FONTNAME",   (8, grand_row_idx), (9, grand_row_idx),   "Helvetica-Bold"),
        ("FONTSIZE",   (8, grand_row_idx), (9, grand_row_idx),   11),
        ("TEXTCOLOR",  (9, grand_row_idx), (9, grand_row_idx),   colors.HexColor(colors_primary)),
    ]
    if paid_amount is not None:
        style_cmds.append(("LINEABOVE", (8, grand_row_idx + 1), (9, grand_row_idx + 1), 0.5, colors.HexColor(colors_border)))

    grand_total_table = Table(totals_rows, colWidths=col_widths)
    grand_total_table.setStyle(TableStyle(style_cmds))
    story.append(grand_total_table)

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes

def build_ledger_pdf(
    company_name:    str,
    company_info:    dict,
    ledger_entries:  list,
    total_billed:    float,
    total_paid:      float,
    running_balance: float,
    start_date:      Optional[str] = None,
    end_date:        Optional[str] = None,
    total_discount_amount: Optional[float] = None,
) -> BytesIO:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=20, leftMargin=20, topMargin=30, bottomMargin=30,
    )
    styles = get_pdf_styles()
    story  = []
    available_width = A4[0] - doc.leftMargin - doc.rightMargin
    primary_color   = colors.HexColor(colors_primary)
    ci = company_info or {}

    logo_img    = _load_logo(ci.get("logo_url"))
    full_address = ", ".join(
        [p for p in [ci.get("address1", "").strip(), ci.get("address2", "").strip()] if p]
    )

    details_table = Table(
        [
            [Paragraph(f"<b>{ci.get('name', 'Company Name')}</b>", styles["CompanyName"])],
            [Paragraph(full_address, styles["CompanySub"])],
            [Paragraph(f"GSTIN: {ci.get('gst', 'N/A')} | Phone: {ci.get('phone', 'N/A')}", styles["CompanySub"])],
        ],
        colWidths=[available_width - 60],
    )

    if logo_img:
        header_table = Table([[logo_img, details_table]], colWidths=[60, available_width - 60])
    else:
        header_table = Table([[details_table]], colWidths=[available_width])

    story.append(header_table)
    story.append(Spacer(1, 15))
    story.append(Paragraph(
        "LEDGER STATEMENT",
        ParagraphStyle(
            name="DocTitle", parent=styles["Heading2"],
            fontSize=14, alignment=1,
            textColor=primary_color, spaceAfter=15,
        ),
    ))

    header_style = ParagraphStyle(
        name="TableHeader", parent=styles["Normal"],
        fontSize=8, textColor=colors.white,
        alignment=1, fontName="Helvetica-Bold",
    )
    table_data = [[
        Paragraph("Date",           header_style),
        Paragraph("Particulars",    header_style),
        Paragraph("Status",         header_style),
        Paragraph("Debit (Rs.)",    header_style),
        Paragraph("Credit (Rs.)",   header_style),
        Paragraph("Balance (Rs.)",  header_style),
    ]]

    for entry in ledger_entries:
        dt = entry["date"].strftime("%d/%m/%Y") if entry["date"] else "-"

        if entry["balance"] <= 0:
            status = "Cleared"
        else:
            status = "Open"

        table_data.append([
            Paragraph(dt,                                         styles["Normal"]),
            Paragraph((entry["description"] or "")[:40],         styles["Normal"]),
            Paragraph(status,                                     styles["Normal"]),
            Paragraph(f"{entry['debit']:,.2f}"   if entry["debit"]   else "0.00", styles["Normal"]),
            Paragraph(f"{entry['credit']:,.2f}"  if entry["credit"]  else "0.00", styles["Normal"]),
            Paragraph(f"{entry['balance']:,.2f}",                 styles["Normal"]),
        ])

    table_data.append([
        "",
        "",
        Paragraph("<b>TOTAL</b>",                       styles["Normal"]),
        Paragraph(f"<b>{total_billed:,.2f}</b>",        styles["Normal"]),
        Paragraph(f"<b>{total_paid:,.2f}</b>",          styles["Normal"]),
        Paragraph(f"<b>{running_balance:,.2f}</b>",     styles["Normal"]),
    ])

    ledger_table = Table(
        table_data,
        colWidths=[65, 170, 50, 75, 75, 85],
        repeatRows=1,
    )
    ledger_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0),  (-1, 0),  primary_color),
        ("TEXTCOLOR",  (0, 0),  (-1, 0),  colors.white),
        ("ALIGN",      (0, 0),  (-1, 0),  "CENTER"),
        ("FONTNAME",   (0, 0),  (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0),  (-1, -1), 8),
        ("GRID",       (0, 0),  (-1, -2), 0.5, colors.HexColor(colors_border)),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f8f9fa")),
        ("LINEABOVE",  (0, -1), (-1, -1), 1, colors.black),
    ]))
    story.append(ledger_table)

    doc.build(story)
    buffer.seek(0)
    return buffer