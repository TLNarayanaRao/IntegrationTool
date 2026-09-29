import os
import uvicorn
from app.main import app

if __name__ == '__main__':
    uvicorn.run(app, host=os.environ.get('MINA_ADMIN_HOST', '0.0.0.0'), port=int(os.environ.get('MINA_ADMIN_PORT', '9080')))
