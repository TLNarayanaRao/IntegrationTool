import os
import uvicorn
from app.main import app
from app.compat import env_value

if __name__ == '__main__':
    uvicorn.run(app, host=env_value('MINA_ADMIN_HOST', '0.0.0.0'), port=int(env_value('MINA_ADMIN_PORT', '9080')))
