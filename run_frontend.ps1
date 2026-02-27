# Run Insight Forge frontend locally
# Loads config from .env (BACKEND_URL, TEMPLATE_PPTX_PATH, etc.)
$FrontendDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$FrontendDir = Join-Path $FrontendDir "frontend"
Set-Location $FrontendDir
streamlit run app.py --server.port 8501
