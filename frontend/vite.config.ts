import { defineConfig } from 'vite'; import react from '@vitejs/plugin-react';
import metadata from './package.json' with { type: 'json' };
export default defineConfig({plugins:[react()], define:{
  'import.meta.env.VITE_APP_VERSION': JSON.stringify(process.env.MINA_VERSION || process.env.VITE_APP_VERSION || metadata.version),
}, server:{proxy:{'/api':'http://127.0.0.1:8787'}}});
