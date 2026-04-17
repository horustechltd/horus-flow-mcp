FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV RAPIDAPI_KEY=""
ENTRYPOINT ["python3", "horus_mcp_public.py", "--transport", "stdio"]
