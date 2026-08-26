FROM python:3.11-slim

WORKDIR /app

# Copy requirements and install
COPY "Back End/requirements.txt" ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Hugging Face Spaces / default container port
EXPOSE 7860

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
