!include "MUI2.nsh"
Name "Integration Fabric"
OutFile "IntegrationFabric-Setup.exe"
InstallDir "$PROGRAMFILES64\Integration Fabric"
RequestExecutionLevel admin
Page directory
Page instfiles
Section
  SetOutPath "$INSTDIR"
  File /r "..\backend\dist\IntegrationFabric\*"
  CreateShortCut "$DESKTOP\Integration Fabric.lnk" "$INSTDIR\IntegrationFabric.exe"
  CreateShortCut "$SMPROGRAMS\Integration Fabric.lnk" "$INSTDIR\IntegrationFabric.exe"
SectionEnd
