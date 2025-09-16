import pdfplumber

def debug_pdf_lines(pdf_file):
    with pdfplumber.open(pdf_file) as pdf:
        all_lines = []
        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text()
            if not text:
                continue
            for i, line in enumerate(text.splitlines()):
                print(f"Page {page_num}, Line {i}: {repr(line)}")
                all_lines.append(line)
        return all_lines

# Run once to see how SBI formats
lines = debug_pdf_lines("Statement1.pdf")
