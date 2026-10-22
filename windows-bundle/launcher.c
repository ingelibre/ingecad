#define UNICODE
#define _UNICODE
#include <windows.h>
#include <wchar.h>

int WINAPI wWinMain(HINSTANCE h, HINSTANCE p, PWSTR args, int show) {
    wchar_t root[32768], python[32768], command[32768];
    if (!GetModuleFileNameW(NULL, root, 32768)) return 1;
    wchar_t *slash = wcsrchr(root, L'\\');
    if (!slash) return 1;
    *slash = 0;
    _snwprintf(python, 32768, L"%ls\\runtime\\pythonw.exe", root);
    int count = _snwprintf(command, 32768, L"\"%ls\" \"%ls\\launch.pyw\" %ls", python, root, args);
    if (count < 0 || count >= 32768) return 1;
    STARTUPINFOW si = {0}; si.cb = sizeof(si);
    PROCESS_INFORMATION pi = {0};
    if (!CreateProcessW(python, command, NULL, NULL, FALSE, 0, NULL, root, &si, &pi)) {
        MessageBoxW(NULL, L"Unable to start IngeCAD. Please reinstall the complete bundle.", L"IngeCAD AI Bundle", MB_ICONERROR);
        return 1;
    }
    CloseHandle(pi.hThread); CloseHandle(pi.hProcess);
    return 0;
}
