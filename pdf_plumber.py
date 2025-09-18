import pdfplumber


PDF_FILE = "iob stmt.pdf"   

def extract_text_from_pdf(pdf_path):
    all_text = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text()
            if text:
                all_text.append(f"=== Page {i} ===\n{text}\n")
            else:
                all_text.append(f"=== Page {i} ===\n(No text found)\n")
    return "\n".join(all_text)

if __name__ == "__main__":
    text_data = extract_text_from_pdf(PDF_FILE)
    
    print(text_data)

    with open("iob_extracted_text.txt", "w", encoding="utf-8") as f:
        f.write(text_data)
