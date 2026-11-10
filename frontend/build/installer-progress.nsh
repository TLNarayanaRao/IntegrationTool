; Assisted electron-builder installer. Use its real extraction/registration
; hooks; the compressed payload does not report separate component progress.
!ifndef BUILD_UNINSTALLER
  !include "WinMessages.nsh"

  Var MinaSetupChecklist

  !if "${PRODUCT_NAME}" == "MINA Studio"
    !define MINA_COMPONENTS_PENDING "[ ] MINA Studio app$\r$\n[ ] Local runtime$\r$\n[ ] Background worker"
    !define MINA_COMPONENTS_DONE "[x] MINA Studio app$\r$\n[x] Local runtime$\r$\n[x] Background worker"
  !else
    !define MINA_COMPONENTS_PENDING "[ ] MINA Control Plane app"
    !define MINA_COMPONENTS_DONE "[x] MINA Control Plane app"
  !endif

  !macro customPageAfterChangeDir
    !define MUI_PAGE_CUSTOMFUNCTION_SHOW MinaShowSetupChecklist
  !macroend

  !macro customHeader
    Function MinaShowSetupChecklist
      StrCpy $MinaSetupChecklist 0
      FindWindow $0 "#32770" "" $HWNDPARENT
      GetDlgItem $1 $0 1016 ; NSIS install details list
      StrCmp $1 0 checklistUnavailable
      GetDlgItem $2 $0 1027 ; NSIS Show details button

      ; Reuse the native list's DPI-scaled rectangle. Leave the progress bar,
      ; status line and navigation buttons in their original positions.
      System::Call '*(i 0, i 0, i 0, i 0) p.r3'
      System::Call 'user32::GetWindowRect(p r1, p r3) i.r4'
      StrCmp $4 0 checklistFree
      System::Call 'user32::MapWindowPoints(p 0, p r0, p r3, i 2)'
      System::Call '*$3(i.r4, i.r5, i.r6, i.r7)'
      IntOp $6 $6 - $4
      IntOp $7 $7 - $5
      ; WS_CHILD | WS_VISIBLE | SS_NOPREFIX, with the normal dialog font.
      System::Call 'user32::CreateWindowExW(i 0, w "STATIC", w "", i 0x50000080, i r4, i r5, i r6, i r7, p r0, p 0, p 0, p 0) p.s'
      Pop $MinaSetupChecklist
      StrCmp $MinaSetupChecklist 0 checklistFree
      SendMessage $1 ${WM_GETFONT} 0 0 $4
      SendMessage $MinaSetupChecklist ${WM_SETFONT} $4 1
      ShowWindow $1 0
      StrCmp $2 0 +2
        ShowWindow $2 0
      SendMessage $MinaSetupChecklist ${WM_SETTEXT} 0 "STR:In progress: Preparing setup and installing files$\r$\n$\r$\n${MINA_COMPONENTS_PENDING}$\r$\n[ ] Windows registration and shortcuts"
      checklistFree:
        System::Free $3
      checklistUnavailable:
    FunctionEnd

    Function MinaPackagedFilesInstalled
      StrCmp $MinaSetupChecklist "" done
      StrCmp $MinaSetupChecklist 0 done
      SendMessage $MinaSetupChecklist ${WM_SETTEXT} 0 "STR:In progress: Registering the app and setting up shortcuts$\r$\n$\r$\n${MINA_COMPONENTS_DONE}$\r$\n[ ] Windows registration and shortcuts"
      System::Call 'user32::UpdateWindow(p $MinaSetupChecklist)'
      done:
    FunctionEnd
  !macroend

  !macro customFiles_x64
    Call MinaPackagedFilesInstalled
  !macroend
  !macro customFiles_arm64
    Call MinaPackagedFilesInstalled
  !macroend
  !macro customFiles_ia32
    Call MinaPackagedFilesInstalled
  !macroend

  !macro customInstall
    ${IfNot} ${Silent}
    ${AndIf} $MinaSetupChecklist != 0
      SendMessage $MinaSetupChecklist ${WM_SETTEXT} 0 "STR:Setup steps completed$\r$\n$\r$\n${MINA_COMPONENTS_DONE}$\r$\n[x] Windows registration and shortcuts"
    ${EndIf}
  !macroend
!endif
