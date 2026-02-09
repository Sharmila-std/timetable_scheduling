import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# CONFIGURATION - REPLACE WITH REAL CREDENTIALS
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = "sarmiladummy@gmail.com"
SENDER_PASSWORD = "kzfcotpgtmsavfgs"
def format_timetable_html(tt_data, title):
    """Generates a simple HTML table for email from timetable data."""
    html = f"<h3>{title}</h3>"
    html += "<table border='1' cellpadding='5' cellspacing='0' style='border-collapse: collapse; width: 100%; font-family: Arial, sans-serif;'>"
    
    # Header
    html += "<tr style='background-color: #f2f2f2;'><th>Day</th>"
    for i in range(1, 9):
        html += f"<th>Slot {i}</th>"
    html += "</tr>"
    
    # Body
    days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
    grid = tt_data.get('timetable', {})
    
    for day in days:
        html += f"<tr><td style='font-weight: bold;'>{day}</td>"
        day_sched = grid.get(day, {})
        for i in range(1, 9):
            slot = day_sched.get(str(i))
            content = "-"
            bg_color = "#ffffff"
            
            if slot:
                code = slot.get('code', '')
                name = slot.get('name', '')
                fac = slot.get('faculty_name', '')
                content = f"<b>{code}</b><br><span style='font-size:0.8em'>{name}</span><br><span style='color:blue; font-size:0.8em'>{fac}</span>"
                
                if slot.get('is_substitution'):
                    bg_color = "#fff3e0"
                    content += "<br><span style='color:red; font-size:0.7em'>(SUB)</span>"
            
            html += f"<td style='background-color: {bg_color}; text-align: center; vertical-align: top;'>{content}</td>"
        html += "</tr>"
    html += "</table><br>"
    return html

import io
from email.mime.base import MIMEBase
from email import encoders
from xhtml2pdf import pisa

def create_pdf(html_content):
    """Converts HTML content to PDF bytes."""
    pdf_buffer = io.BytesIO()
    pisa_status = pisa.CreatePDF(io.BytesIO(html_content.encode("utf-8")), dest=pdf_buffer)
    if pisa_status.err:
        print(f"PDF generation error: {pisa_status.err}")
        return None
    return pdf_buffer.getvalue()

def send_timetable_update_email(advisor_email, batch_name, original_tt, temp_tt_data):
    """Sends an email with PDF attachment."""
    if not advisor_email:
        print("ERROR: No Advisor Email provided.")
        return False

    msg = MIMEMultipart("alternative")
    msg['Subject'] = f"Timetable Update for {batch_name}"
    msg['From'] = SENDER_EMAIL
    msg['To'] = advisor_email

    # Generate HTML Content
    html_content = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; }}
            table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; font-size: 10px; }}
            th {{ background-color: #f2f2f2; }}
        </style>
    </head>
    <body>
        <h2>Timetable Update Notification</h2>
        <p>Dear Class Advisor,</p>
        <p>This is an automated notification regarding a schedule update for <b>{batch_name}</b>.</p>
        
        {format_timetable_html(temp_tt_data, "Temporary Substitution Schedule")}
        
        <p>For reference, here is the original schedule:</p>
        {format_timetable_html(original_tt, "Original Schedule")}
        
        <p>Please find the PDF copy attached.</p>
        <p>Regards,<br>AutoScheduler Admin</p>
    </body>
    </html>
    """
    
    # Attach HTML Body
    msg.attach(MIMEText(html_content, "html"))
    
    # Generate and Attach PDF
    pdf_bytes = create_pdf(html_content)
    if pdf_bytes:
        part = MIMEBase('application', "octet-stream")
        part.set_payload(pdf_bytes)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename="Timetable_{batch_name}.pdf"')
        msg.attach(part)
    else:
        print("Warning: Failed to generate PDF attachment.")

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, advisor_email, msg.as_string())
        server.quit()
        
        print(f"EMAIL SENT TO {advisor_email} with subject '{msg['Subject']}' and PDF attachment")
        return True
    
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False

def send_original_timetable_email(advisor_email, batch_name, original_tt):
    """Sends an email with Original Timetable PDF."""
    if not advisor_email:
        print("ERROR: No Advisor Email provided.")
        return False

    msg = MIMEMultipart("alternative")
    msg['Subject'] = f"Original Timetable for {batch_name}"
    msg['From'] = SENDER_EMAIL
    msg['To'] = advisor_email

    # Generate HTML Content
    html_content = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; }}
            table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; font-size: 10px; }}
            th {{ background-color: #f2f2f2; }}
        </style>
    </head>
    <body>
        <h2>Original Timetable - {batch_name}</h2>
        <p>Dear Class Advisor,</p>
        <p>Please find the original timetable for <b>{batch_name}</b> attached.</p>
        
        {format_timetable_html(original_tt, "Original Schedule")}
        
        <p>Regards,<br>AutoScheduler Admin</p>
    </body>
    </html>
    """
    
    # Attach HTML Body
    msg.attach(MIMEText(html_content, "html"))
    
    # Generate and Attach PDF
    pdf_bytes = create_pdf(html_content)
    if pdf_bytes:
        part = MIMEBase('application', "octet-stream")
        part.set_payload(pdf_bytes)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename="Original_Timetable_{batch_name}.pdf"')
        msg.attach(part)

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, advisor_email, msg.as_string())
        server.quit()
        
        print(f"EMAIL SENT TO {advisor_email} with subject '{msg['Subject']}' and PDF attachment")
        return True
    
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False
