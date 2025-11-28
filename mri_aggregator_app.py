import os
import re
import json
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

import pdfplumber
from openai import OpenAI  # new-style client

# ==========================
# CONFIG – EDIT THESE
# ==========================

# 1) Put your OpenAI API key here
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# 2) Default folder where MRI PDF reports are stored
DEFAULT_PDF_FOLDER = os.path.expanduser("~/Documents/MRI_Reports")

# 3) Default output folder for JSON + text/CSV report
DEFAULT_OUTPUT_FOLDER = os.path.expanduser("~/Documents/MRI_Outputs")

# 4) Model to use with Responses API
LLM_MODEL = "gpt-4.1-mini"


# ==========================
# HELPER FUNCTIONS
# ==========================

def load_pdf_text(pdf_path: str) -> str:
    """
    Load all text from a multi-page PDF using pdfplumber.
    Joins all pages with newlines.
    """
    text_pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text_pages.append(page_text)
    return "\n".join(text_pages)


def normalize_text(text: str) -> str:
    """Normalize line endings and odd spaces."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ")  # non-breaking space
    return text


# ==========================
# PATIENT NAME EXTRACTION
# ==========================

def extract_patient_name(text: str) -> str:
    """
    Best-effort extraction of patient/customer name from the report text.

    Looks for common patterns like:
      - 'Patient Name: John Doe'
      - 'Patient: John Doe'
      - 'Name: John Doe'

    Returns 'Unknown' if nothing obvious is found.
    """
    norm = normalize_text(text)

    patterns = [
        r"patient name[:\-]\s*(.+)",
        r"patient[:\-]\s*(.+)",
        r"name[:\-]\s*(.+)",
    ]

    for pat in patterns:
        m = re.search(pat, norm, flags=re.IGNORECASE)
        if m:
            line = m.group(1).strip()
            # Cut off at common separators like double spaces or DOB
            line = re.split(r"\s{2,}|dob", line, flags=re.IGNORECASE)[0].strip()
            # Avoid extremely long garbage
            if 0 < len(line) <= 80:
                return line

    return "Unknown"


# ==========================
# SECTION EXTRACTION
# ==========================

def extract_section_by_heading(text: str, heading: str, stop_headings: list[str]) -> str | None:
    """
    Generic helper to extract a section starting at a given heading
    and ending before the next stop heading.

    heading: e.g. "findings", "impression"
    stop_headings: list like ["impression", "conclusion", "discussion", "report", "findings"]

    Returns None if the heading is not found.
    """
    if not text:
        return None

    norm = normalize_text(text)
    low = norm.lower()

    # Heading at line start, optionally numbered and with punctuation
    heading_match = re.search(
        rf"^\s*(?:\d+\s*[\.\)])?\s*{heading}s?\b\s*[:\-–—.]?",
        low,
        flags=re.MULTILINE,
    )
    if not heading_match:
        return None

    start_idx = heading_match.end()
    end_idx = len(norm)

    for kw in stop_headings:
        m = re.search(
            rf"\b{kw}s?\b\s*[:\-–—.]?",
            low[start_idx:],
        )
        if m:
            candidate = start_idx + m.start()
            if candidate < end_idx:
                end_idx = candidate

    section_text = norm[start_idx:end_idx].strip()
    return section_text or None


def extract_findings_section(text: str) -> str | None:
    """Extract FINDINGS section if present."""
    stop_headings = ["impression", "conclusion", "discussion", "report"]
    return extract_section_by_heading(text, "findings", stop_headings)


def extract_impression_section(text: str) -> str | None:
    """Extract IMPRESSION section if present."""
    stop_headings = ["conclusion", "discussion", "report", "findings"]
    return extract_section_by_heading(text, "impression", stop_headings)


# ==========================
# LLM CALLS (PER REPORT)
# ==========================

def summarize_section_structured(client: OpenAI, section_text: str, source_label: str) -> dict:
    """
    Given text from either:
      - FINDINGS section
      - IMPRESSION section
      - or full report text (fallback),
    ask the LLM to produce a structured JSON with:
      - summary: a concise textual summary (1–3 sentences)
      - severity_label: one of ["none/normal", "mild", "moderate", "severe", "uncertain"]
      - severity_score: integer 0–5 (0 = normal, 5 = very severe)

    source_label: "findings" | "impression" | "full_report"
    """
    prompt = f"""
You are an expert radiologist.

You will receive MRI report text that may be:
- the FINDINGS section,
- the IMPRESSION section, or
- the full report text.

The source type is: {source_label}

Your job:

1. Read the content carefully.
2. Produce a short, clinically accurate summary (1–3 sentences) that captures
   the key abnormal findings and overall impression of severity.
3. Assign a severity label and numeric score:

   - severity_label: one of
       "none/normal", "mild", "moderate", "severe", "uncertain"
   - severity_score: integer from 0 to 5
       0 = no abnormal findings
       1 = very mild/minimal
       2 = mild
       3 = moderate
       4 = marked/severe
       5 = very severe / critical

Return ONLY a JSON object with this exact schema:

{{
  "summary": "<1-3 sentence textual summary>",
  "severity_label": "<one of: none/normal, mild, moderate, severe, uncertain>",
  "severity_score": <integer 0-5>
}}

Do not include treatment recommendations or future plans—only describe the imaging-based severity.

Here is the text:

\"\"\"{section_text}\"\"\"
"""

    # Use Responses API, no response_format kw to keep compatibility
    resp = client.responses.create(
        model=LLM_MODEL,
        input=prompt,
    )

    # Convenience: get combined text output
    raw = resp.output_text.strip()

    # Strip ```json fences if present
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*", "", raw).strip()
        if raw.endswith("```"):
            raw = raw[:-3].strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {
            "summary": section_text[:300] + ("..." if len(section_text) > 300 else ""),
            "severity_label": "uncertain",
            "severity_score": 3,
            "raw_llm_output": raw,
        }
    return data


# ==========================
# GUI LOGIC
# ==========================

class MRIApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("MRI Report Per-Study Summary")

        # Make sure default folders exist
        os.makedirs(DEFAULT_PDF_FOLDER, exist_ok=True)
        os.makedirs(DEFAULT_OUTPUT_FOLDER, exist_ok=True)

        # Input folder
        self.folder_label = tk.Label(root, text="Input PDF Folder:")
        self.folder_label.grid(row=0, column=0, sticky="w", padx=5, pady=5)

        self.folder_var = tk.StringVar(value=DEFAULT_PDF_FOLDER)
        self.folder_entry = tk.Entry(root, textvariable=self.folder_var, width=60)
        self.folder_entry.grid(row=0, column=1, padx=5, pady=5, sticky="we")

        self.browse_btn = tk.Button(root, text="Browse...", command=self.browse_folder)
        self.browse_btn.grid(row=0, column=2, padx=5, pady=5)

        # Output folder
        self.out_label = tk.Label(root, text="Output Folder:")
        self.out_label.grid(row=1, column=0, sticky="w", padx=5, pady=5)

        self.out_var = tk.StringVar(value=DEFAULT_OUTPUT_FOLDER)
        self.out_entry = tk.Entry(root, textvariable=self.out_var, width=60)
        self.out_entry.grid(row=1, column=1, padx=5, pady=5, sticky="we")

        self.out_browse_btn = tk.Button(root, text="Browse...", command=self.browse_output_folder)
        self.out_browse_btn.grid(row=1, column=2, padx=5, pady=5)

        # Run button
        self.run_button = tk.Button(root, text="Run Per-Report Summaries", command=self.run_aggregation)
        self.run_button.grid(row=2, column=0, columnspan=3, pady=10)

        # Text output
        self.output_text = scrolledtext.ScrolledText(root, height=25, width=100, wrap=tk.WORD)
        self.output_text.grid(row=3, column=0, columnspan=3, padx=5, pady=5, sticky="nsew")

        # Configure resize behavior
        root.grid_rowconfigure(3, weight=1)
        root.grid_columnconfigure(1, weight=1)

        # OpenAI client
        if not OPENAI_API_KEY or "YOUR_OPENAI_API_KEY_HERE" in OPENAI_API_KEY:
            messagebox.showwarning(
                "API Key Missing",
                "Please set your OpenAI API key in the script (OPENAI_API_KEY).",
            )
            self.client = None
        else:
            self.client = OpenAI(api_key=OPENAI_API_KEY)

    def browse_folder(self):
        folder_selected = filedialog.askdirectory(initialdir=self.folder_var.get())
        if folder_selected:
            self.folder_var.set(folder_selected)

    def browse_output_folder(self):
        folder_selected = filedialog.askdirectory(initialdir=self.out_var.get())
        if folder_selected:
            self.out_var.set(folder_selected)

    def run_aggregation(self):
        if not self.client:
            messagebox.showerror("Error", "OpenAI client not initialized. Check API key.")
            return

        input_folder = self.folder_var.get().strip()
        output_folder = self.out_var.get().strip()

        if not os.path.isdir(input_folder):
            messagebox.showerror("Error", f"Input folder does not exist:\n{input_folder}")
            return
        if not os.path.isdir(output_folder):
            messagebox.showerror("Error", f"Output folder does not exist:\n{output_folder}")
            return

        # Find all PDF files
        pdf_files = [
            os.path.join(input_folder, f)
            for f in os.listdir(input_folder)
            if f.lower().endswith(".pdf")
        ]
        pdf_files.sort()
        if not pdf_files:
            messagebox.showinfo("No PDFs", "No PDF files found in the selected folder.")
            return

        self.output_text.delete("1.0", tk.END)
        self.output_text.insert(tk.END, f"Found {len(pdf_files)} PDF files.\n\n")
        self.root.update_idletasks()

        per_report_rows = []

        for pdf_path in pdf_files:
            basename = os.path.basename(pdf_path)
            self.output_text.insert(tk.END, f"Processing: {basename}\n")
            self.root.update_idletasks()

            try:
                full_text = load_pdf_text(pdf_path)
            except Exception as e:
                self.output_text.insert(
                    tk.END,
                    f"  Error reading PDF: {e}\n\n",
                )
                continue

            # Extract patient/customer name
            patient_name = extract_patient_name(full_text) or "Unknown"

            # Try FINDINGS first, then IMPRESSION, else full report
            findings_text = extract_findings_section(full_text)
            impression_text = extract_impression_section(full_text)

            if findings_text:
                section_text = findings_text
                source_label = "findings"
                self.output_text.insert(
                    tk.END,
                    "  Using FINDINGS section for summary + severity.\n",
                )
            elif impression_text:
                section_text = impression_text
                source_label = "impression"
                self.output_text.insert(
                    tk.END,
                    "  No FINDINGS section; using IMPRESSION section.\n",
                )
            else:
                section_text = full_text
                source_label = "full_report"
                self.output_text.insert(
                    tk.END,
                    "  No FINDINGS or IMPRESSION heading; using full report text.\n",
                )

            self.root.update_idletasks()

            try:
                structured = summarize_section_structured(self.client, section_text, source_label)
            except Exception as e:
                self.output_text.insert(
                    tk.END,
                    f"  Error during LLM call: {e}\n\n",
                )
                continue

            summary = structured.get("summary", "").strip()
            severity_label = structured.get("severity_label", "uncertain")
            severity_score = structured.get("severity_score", 3)

            per_report_rows.append(
                {
                    "file": basename,
                    "patient_name": patient_name,
                    "summary": summary,
                    "severity_label": severity_label,
                    "severity_score": severity_score,
                }
            )

            self.output_text.insert(
                tk.END,
                f"  Done. Severity: {severity_label} (score {severity_score}).\n\n",
            )
            self.root.update_idletasks()

        if not per_report_rows:
            self.output_text.insert(
                tk.END,
                "\nNo reports produced valid summaries.\n",
            )
            return

        # ==========================
        # Display table-style summary
        # ==========================
        self.output_text.insert(tk.END, "\nPer-report Summary (one row per PDF):\n\n")

        header = f"{'Report File':30s}  {'Customer Name':25s}  {'Severity':10s}  Summary\n"
        self.output_text.insert(tk.END, header)
        self.output_text.insert(tk.END, "-" * 120 + "\n")

        for row in per_report_rows:
            file_col = row["file"][:30].ljust(30)
            name_col = row["patient_name"][:25].ljust(25)
            sev_col = f"{row['severity_label']} ({row['severity_score']})"
            sev_col = sev_col[:10].ljust(10)
            summary_col = row["summary"].replace("\n", " ")
            self.output_text.insert(
                tk.END,
                f"{file_col}  {name_col}  {sev_col}  {summary_col}\n",
            )

        # ==========================
        # Save CSV + JSON
        # ==========================
        base_name = "mri_per_report_summary"
        csv_path = os.path.join(output_folder, base_name + ".csv")
        json_path = os.path.join(output_folder, base_name + ".json")

        try:
            import csv

            with open(csv_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(
                    ["report_file", "patient_name", "severity_label", "severity_score", "summary"]
                )
                for row in per_report_rows:
                    writer.writerow(
                        [
                            row["file"],
                            row["patient_name"],
                            row["severity_label"],
                            row["severity_score"],
                            row["summary"],
                        ]
                    )

            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(per_report_rows, f, indent=2)

            self.output_text.insert(
                tk.END,
                f"\nSaved CSV summary to: {csv_path}\nSaved JSON summary to: {json_path}\n",
            )
        except Exception as e:
            self.output_text.insert(
                tk.END,
                f"\nError saving CSV/JSON: {e}\n",
            )


def main():
    root = tk.Tk()
    app = MRIApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
