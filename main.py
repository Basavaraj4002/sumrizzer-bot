from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import pandas as pd
import numpy as np
import pdfplumber
import io
import re
import logging
import json

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def catch_exceptions(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        logger.error(f"Unhandled exception: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

def extract_marks(pdf_file):
    try:
        with pdfplumber.open(io.BytesIO(pdf_file)) as pdf:
            all_students = []
            pattern = r'(\d+)\s+([A-Z0-9]+)\s+(\d+)\s+\(TH\)\s*,\s*(\d+)\s+\(PR\)'

            for page_number, page in enumerate(pdf.pages, 1):
                text = page.extract_text()
                if not text:
                    logger.warning(f"No text found on page {page_number}")
                    continue
                
                matches = re.finditer(pattern, text)
                for match in matches:
                    try:
                        sl_no, usn, theory, practical = match.groups()
                        all_students.append({
                            'SL_NO': int(sl_no),
                            'USN': usn.strip(),
                            'Theory': int(theory),
                            'Practical': int(practical)
                        })
                    except Exception as e:
                        logger.warning(f"Skipping row due to error: {e}")
            
            if not all_students:
                raise ValueError("No valid student records found in PDF")
            
            return pd.DataFrame(all_students)

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"PDF processing error: {str(e)}")

def analyze_marks(df):
    df['Total'] = df['Theory'] + df['Practical']
    df['Theory_Eligible'] = df['Theory'] >= 10
    df['Practical_Eligible'] = df['Practical'] >= 10
    df['Overall_Eligible'] = (df['Total'] >= 20) & df['Theory_Eligible'] & df['Practical_Eligible']

    df['Theory_Eligible'] = df['Theory_Eligible'].map({True: 'Yes', False: 'No'})
    df['Practical_Eligible'] = df['Practical_Eligible'].map({True: 'Yes', False: 'No'})
    df['Overall_Eligible'] = df['Overall_Eligible'].map({True: 'Yes', False: 'No'})

    summary = {
        'total_students': int(len(df)),
        'eligible_count': int(len(df[df['Overall_Eligible'] == 'Yes'])),
        'not_eligible_count': int(len(df[df['Overall_Eligible'] == 'No'])),
        'pass_percentage': round(len(df[df['Overall_Eligible'] == 'Yes']) / len(df) * 100, 2),
        'theory_stats': {
            'average': round(df['Theory'].mean(), 2),
            'max': int(df['Theory'].max()),
            'min': int(df['Theory'].min()),
            'passed': int(len(df[df['Theory'] >= 10])),
            'pass_percentage': round(len(df[df['Theory'] >= 10]) / len(df) * 100, 2)
        },
        'practical_stats': {
            'average': round(df['Practical'].mean(), 2),
            'max': int(df['Practical'].max()),
            'min': int(df['Practical'].min()),
            'passed': int(len(df[df['Practical'] >= 10])),
            'pass_percentage': round(len(df[df['Practical'] >= 10]) / len(df) * 100, 2)
        },
        'top_students': df.nlargest(5, 'Total').to_dict('records'),
        'bottom_students': df.nsmallest(5, 'Total').to_dict('records'),
        'all_students': df.to_dict('records')
    }

    return JSONResponse(content=json.loads(json.dumps(summary, default=str)))

@app.post("/summarize-marks/")
async def summarize_marks(file: UploadFile = File(...)):
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(400, "Only PDF files allowed")
    
    file_content = await file.read()
    if not file_content:
        raise HTTPException(400, "Empty file received")
    
    df = extract_marks(file_content)
    return analyze_marks(df)

@app.get("/")
async def root():
    return {"message": "Marks Summarizer API"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
