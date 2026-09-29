!include "MUI2.nsh"
Name "MINA"
OutFile "MINA-Setup.exe"
InstallDir "$PROGRAMFILES64\MINA"
RequestExecutionLevel admin
Page directory
Page instfiles
Section
  SetOutPath "$INSTDIR"
  File /r "..\backend\dist\MINA\*"
  CreateShortCut "$DESKTOP\MINA.lnk" "$INSTDIR\MINA.exe"
  CreateShortCut "$SMPROGRAMS\MINA.lnk" "$INSTDIR\MINA.exe"
SectionEnd
