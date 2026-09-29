import os
import uvicorn
from app.main import app

if __name__ == '__main__':
    port = int(os.environ.get('MINA_PORT', '8787'))
    uvicorn.run(app, host='127.0.0.1', port=port, log_level=os.environ.get('MINA_LOG_LEVEL', 'info'))
