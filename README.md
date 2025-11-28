# DeepScan MRI Agent
DeepScan MRI Agent
AI Radiology Report Summarization Agent

Automatically extracts key clinical insights from MRI PDF reports using AI-driven Findings/Impression analysis.

🧠 Overview

DeepScan MRI Agent is an AI-powered application that reads MRI radiology PDF reports, extracts relevant sections (Findings, Impression, or full report text), and generates:

✔ Summaries (1–3 sentences)

✔ Severity ratings (mild / moderate / severe / none / uncertain)

✔ Severity scores (0–5)

✔ Per-report CSV + JSON output

✔ Clean GUI experience

Designed for medical practices, diagnostic teams, and researchers who need fast, consistent interpretation of radiology report text.

This agent uses OpenAI’s Responses API for robust summarization and clinical language understanding.

🚀 Key Features
AI-Powered NLP Radiology Summaries

Automatically extracts and interprets:

FINDINGS section (preferred)

IMPRESSION section (fallback)

Entire report text (if no sections present)

Severity Classification

LLM assigns:

Label: none/normal, mild, moderate, severe, uncertain

Numerical score: 0 to 5

Batch Processing

Feed a folder of MRI PDFs → get results for each file.

Export

Outputs:

mri_per_report_summary.csv

mri_per_report_summary.json

GUI

Simple cross-platform GUI built with Tkinter.

📂 Project Structure
DeepScan-MRI-Agent/
│
├── mri_aggregator_app.py        # Main application
├── README.md                    # Documentation
├── assets/                      # Logos, icons, branding
└── output/                      # CSV + JSON summaries

🔧 Requirements

Python 3.12+

pdfplumber

openai>=1.0

tkinter (default on macOS/Linux; installable on Windows)

Install dependencies:

pip install pdfplumber openai

Set API Key

Edit in mri_aggregator_app.py:

OPENAI_API_KEY = "YOUR_OPENAI_KEY_HERE"

Run the App
python mri_aggregator_app.py

🖥 Supported Platforms

macOS (Intel + Apple Silicon)

Windows 10/11

Linux x86_64

Disclaimer

This agent is not a medical device.
It is intended for research and workflow assistance only, not clinical diagnosis.


License

MIT License.


