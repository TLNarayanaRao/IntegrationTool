const path=require('node:path');
module.exports={
  extends:null,
  appId:'io.mina.controlplane.desktop',productName:'MINA Control Plane',
  directories:{app:__dirname,output:process.env.MINA_CP_OUTPUT || path.join(__dirname,'../release-control-plane')},
  extraMetadata:{version:process.env.MINA_CP_VERSION || require('../package.json').version},
  extraResources:[],
  electronDist:path.join(__dirname,'../node_modules/electron/dist'),
  electronVersion:require('../node_modules/electron/package.json').version,
  files:['main.cjs','policy.cjs','preload.cjs','connect.html','connect.css','connect.js','package.json','!node_modules/**/*'],
  asar:true,
  win:{target:['nsis'],artifactName:'MINAControlPlane-${version}-Setup.${ext}'},
  nsis:{oneClick:false,perMachine:false,allowToChangeInstallationDirectory:true,createDesktopShortcut:true,createStartMenuShortcut:true,shortcutName:'MINA Control Plane'}
};
