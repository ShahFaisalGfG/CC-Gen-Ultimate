// shell_extension.cpp - IExplorerCommand COM in-process server for Explorer's right-click menu
//
// Video and audio files get "Generate Subtitles with CC-Gen-Ultimate"; subtitle files get
// "Translate with CC-Gen-Ultimate" and "Transliterate with CC-Gen-Ultimate". Each entry is its own
// CLSID (registered by the installers under SystemFileAssociations) and starts the app with
// `--tab <key>` before the selected paths. An app window that is already open takes the files
// (ccgen/utils/single_instance.py), so a long selection split over several starts ends in one
// window. When the app can't be started, a message box says so.

#define WIN32_LEAN_AND_MEAN
#define STRICT
#include <windows.h>
#include <shlobj.h>
#include <shobjidl.h>
#include <objbase.h>
#include <cwctype>
#include <new>
#include <string>
#include <vector>

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

static HMODULE g_hModule  = nullptr;
static LONG    g_refCount = 0;

// ---------------------------------------------------------------------------
// CLSIDs - keep in step with the [Registry] sections of installer/ccgenultimate_*_installer.iss
// ---------------------------------------------------------------------------

// {5E1DC6F3-4ECF-47F4-BB26-F8D3097DE182} - Generate Subtitles (video and audio files)
static const GUID CLSID_CcGenSubtitles = {
    0x5E1DC6F3, 0x4ECF, 0x47F4,
    {0xBB, 0x26, 0xF8, 0xD3, 0x09, 0x7D, 0xE1, 0x82}
};

// {00B71345-AC5E-4B8C-B19B-4B7A583417F9} - Translate (subtitle files)
static const GUID CLSID_CcGenTranslate = {
    0x00B71345, 0xAC5E, 0x4B8C,
    {0xB1, 0x9B, 0x4B, 0x7A, 0x58, 0x34, 0x17, 0xF9}
};

// {3382A0C2-1398-4A61-B731-53C435DEF132} - Transliterate (subtitle files)
static const GUID CLSID_CcGenTransliterate = {
    0x3382A0C2, 0x1398, 0x4A61,
    {0xB7, 0x31, 0x53, 0xC4, 0x35, 0xDE, 0xF1, 0x32}
};

// One menu entry: its CLSID, its text, and the app tab its files open in (app.py's --tab).
struct CommandInfo
{
    const GUID*    clsid;
    const wchar_t* title;
    const wchar_t* tab;
};

static const CommandInfo g_commands[] = {
    { &CLSID_CcGenSubtitles,     L"Generate Subtitles with CC-Gen-Ultimate", L"generate" },
    { &CLSID_CcGenTranslate,     L"Translate with CC-Gen-Ultimate",          L"translate" },
    { &CLSID_CcGenTransliterate, L"Transliterate with CC-Gen-Ultimate",      L"transliterate" },
};

// CreateProcessW takes a command line of at most 32,767 characters; a longer selection is split
// over several starts, which the open window collects.
static const size_t MAX_COMMAND_LINE = 32000;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

static std::wstring dllDirectory()
{
    wchar_t buf[MAX_PATH] = {};
    GetModuleFileNameW(g_hModule, buf, MAX_PATH);
    std::wstring s(buf);
    auto pos = s.rfind(L'\\');
    if (pos != std::wstring::npos) s.resize(pos);
    return s;
}

static std::wstring quoted(const std::wstring& s)
{
    return L"\"" + s + L"\"";
}

static HRESULT copyToTaskMem(const std::wstring& text, LPWSTR* out)
{
    size_t len = text.size() + 1;
    *out = static_cast<LPWSTR>(CoTaskMemAlloc(len * sizeof(wchar_t)));
    if (!*out) return E_OUTOFMEMORY;
    wcscpy_s(*out, len, text.c_str());
    return S_OK;
}

// The file system paths of the selected items; items without one (inside a zip, say) are skipped.
static std::vector<std::wstring> selectedPaths(IShellItemArray* items)
{
    std::vector<std::wstring> paths;
    DWORD count = 0;
    if (!items || FAILED(items->GetCount(&count))) return paths;
    paths.reserve(count);
    for (DWORD i = 0; i < count; i++) {
        IShellItem* item = nullptr;
        if (SUCCEEDED(items->GetItemAt(i, &item))) {
            LPWSTR path = nullptr;
            if (SUCCEEDED(item->GetDisplayName(SIGDN_FILESYSPATH, &path))) {
                paths.emplace_back(path);
                CoTaskMemFree(path);
            }
            item->Release();
        }
    }
    return paths;
}

// `"<exe>" --tab <tab> "<path>" ...`, split so that no command line is too long for CreateProcessW.
static std::vector<std::wstring> commandLines(const std::wstring& exePath, const wchar_t* tab,
                                              const std::vector<std::wstring>& paths)
{
    const std::wstring start = quoted(exePath) + L" --tab " + tab;
    std::vector<std::wstring> lines;
    std::wstring line = start;
    for (const auto& path : paths) {
        std::wstring argument = L" " + quoted(path);
        if (line.size() > start.size() && line.size() + argument.size() > MAX_COMMAND_LINE) {
            lines.push_back(line);
            line = start;
        }
        line += argument;
    }
    lines.push_back(line);
    return lines;
}

// The top-level window of the Explorer view the command runs in, or nullptr when the site has none.
static HWND siteWindow(IUnknown* site)
{
    if (!site) return nullptr;
    HWND hwnd = nullptr;
    IOleWindow* window = nullptr;
    if (SUCCEEDED(site->QueryInterface(IID_PPV_ARGS(&window)))) {
        window->GetWindow(&hwnd);
        window->Release();
    }
    if (!hwnd) {
        IServiceProvider* services = nullptr;
        if (SUCCEEDED(site->QueryInterface(IID_PPV_ARGS(&services)))) {
            if (SUCCEEDED(services->QueryService(SID_STopLevelBrowser, IID_PPV_ARGS(&window)))) {
                window->GetWindow(&hwnd);
                window->Release();
            }
            services->Release();
        }
    }
    return hwnd ? GetAncestor(hwnd, GA_ROOT) : nullptr;
}

// Say that the app didn't start, with Windows' reason, instead of the menu doing nothing.
static void reportLaunchFailure(HWND owner, DWORD error)
{
    LPWSTR reason = nullptr;
    FormatMessageW(FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
                   nullptr, error, 0, reinterpret_cast<LPWSTR>(&reason), 0, nullptr);
    std::wstring because = reason ? reason : L"";
    if (reason) LocalFree(reason);
    while (!because.empty() && iswspace(because.back())) because.pop_back();

    std::wstring text = L"CC-Gen-Ultimate didn't start, so the files weren't opened.\n\nWindows said: ";
    text += because.empty() ? L"unknown error" : because;
    text += L" (error " + std::to_wstring(error) + L")";
    text += L"\n\nIf CC-Gen-Ultimate was moved or removed, install it again, then try again.";
    MessageBoxW(owner, text.c_str(), L"CC-Gen-Ultimate", MB_OK | MB_ICONERROR);
}

// ---------------------------------------------------------------------------
// CcGenCommand - IExplorerCommand + IObjectWithSite (for the owner window of the error message)
// ---------------------------------------------------------------------------

class CcGenCommand : public IExplorerCommand, public IObjectWithSite
{
    LONG               _refs;
    const CommandInfo& _info;
    IUnknown*          _site;

public:
    explicit CcGenCommand(const CommandInfo& info) : _refs(1), _info(info), _site(nullptr)
    {
        InterlockedIncrement(&g_refCount);
    }

    ~CcGenCommand()
    {
        if (_site) _site->Release();
        InterlockedDecrement(&g_refCount);
    }

    // ── IUnknown ──────────────────────────────────────────────────────────

    STDMETHODIMP QueryInterface(REFIID riid, void** ppv) override
    {
        if (!ppv) return E_POINTER;
        if (IsEqualIID(riid, IID_IUnknown) || IsEqualIID(riid, IID_IExplorerCommand)) {
            *ppv = static_cast<IExplorerCommand*>(this);
        } else if (IsEqualIID(riid, IID_IObjectWithSite)) {
            *ppv = static_cast<IObjectWithSite*>(this);
        } else {
            *ppv = nullptr;
            return E_NOINTERFACE;
        }
        AddRef();
        return S_OK;
    }

    STDMETHODIMP_(ULONG) AddRef() override
    {
        return InterlockedIncrement(&_refs);
    }

    STDMETHODIMP_(ULONG) Release() override
    {
        LONG r = InterlockedDecrement(&_refs);
        if (r == 0) delete this;
        return r;
    }

    // ── IObjectWithSite ───────────────────────────────────────────────────

    STDMETHODIMP SetSite(IUnknown* site) override
    {
        if (site) site->AddRef();
        if (_site) _site->Release();
        _site = site;
        return S_OK;
    }

    STDMETHODIMP GetSite(REFIID riid, void** ppv) override
    {
        if (!ppv) return E_POINTER;
        *ppv = nullptr;
        return _site ? _site->QueryInterface(riid, ppv) : E_FAIL;
    }

    // ── IExplorerCommand ──────────────────────────────────────────────────

    STDMETHODIMP GetTitle(IShellItemArray*, LPWSTR* ppszName) override
    {
        if (!ppszName) return E_POINTER;
        return copyToTaskMem(_info.title, ppszName);
    }

    STDMETHODIMP GetIcon(IShellItemArray*, LPWSTR* ppszIcon) override
    {
        if (!ppszIcon) return E_POINTER;
        return copyToTaskMem(dllDirectory() + L"\\icons\\CCGenUltimate.ico", ppszIcon);
    }

    STDMETHODIMP GetToolTip(IShellItemArray*, LPWSTR* ppszInfotip) override
    {
        if (!ppszInfotip) return E_POINTER;
        *ppszInfotip = nullptr;
        return E_NOTIMPL;
    }

    STDMETHODIMP GetCanonicalName(GUID* pguid) override
    {
        if (!pguid) return E_POINTER;
        *pguid = *_info.clsid;
        return S_OK;
    }

    STDMETHODIMP GetState(IShellItemArray*, BOOL, EXPCMDSTATE* pState) override
    {
        if (!pState) return E_POINTER;
        *pState = ECS_ENABLED;
        return S_OK;
    }

    STDMETHODIMP GetFlags(EXPCMDFLAGS* pFlags) override
    {
        if (!pFlags) return E_POINTER;
        *pFlags = ECF_DEFAULT;
        return S_OK;
    }

    STDMETHODIMP EnumSubCommands(IEnumExplorerCommand** ppEnum) override
    {
        if (!ppEnum) return E_POINTER;
        *ppEnum = nullptr;
        return E_NOTIMPL;
    }

    STDMETHODIMP Invoke(IShellItemArray* psia, IBindCtx*) override
    {
        const std::wstring exePath = dllDirectory() + L"\\CC-Gen-Ultimate.exe";
        for (auto& cmdLine : commandLines(exePath, _info.tab, selectedPaths(psia))) {
            STARTUPINFOW si        = {};
            si.cb                  = sizeof(si);
            PROCESS_INFORMATION pi = {};
            if (!CreateProcessW(exePath.c_str(), cmdLine.data(), nullptr, nullptr, FALSE, CREATE_NO_WINDOW,
                                nullptr, nullptr, &si, &pi)) {
                // The message box has told the user, so Explorer has nothing more to report.
                reportLaunchFailure(siteWindow(_site), GetLastError());
                return S_OK;
            }
            CloseHandle(pi.hProcess);
            CloseHandle(pi.hThread);
        }
        return S_OK;
    }
};

// ---------------------------------------------------------------------------
// CcGenClassFactory - IClassFactory, one per menu entry
// ---------------------------------------------------------------------------

class CcGenClassFactory : public IClassFactory
{
    LONG               _refs;
    const CommandInfo& _info;

public:
    explicit CcGenClassFactory(const CommandInfo& info) : _refs(1), _info(info)
    {
        InterlockedIncrement(&g_refCount);
    }

    ~CcGenClassFactory()
    {
        InterlockedDecrement(&g_refCount);
    }

    // IUnknown
    STDMETHODIMP QueryInterface(REFIID riid, void** ppv) override
    {
        if (!ppv) return E_POINTER;
        if (IsEqualIID(riid, IID_IUnknown) || IsEqualIID(riid, IID_IClassFactory)) {
            *ppv = static_cast<IClassFactory*>(this);
            AddRef();
            return S_OK;
        }
        *ppv = nullptr;
        return E_NOINTERFACE;
    }

    STDMETHODIMP_(ULONG) AddRef() override { return InterlockedIncrement(&_refs); }

    STDMETHODIMP_(ULONG) Release() override
    {
        LONG r = InterlockedDecrement(&_refs);
        if (r == 0) delete this;
        return r;
    }

    // IClassFactory
    STDMETHODIMP CreateInstance(IUnknown* outer, REFIID riid, void** ppv) override
    {
        if (!ppv) return E_POINTER;
        *ppv = nullptr;
        if (outer) return CLASS_E_NOAGGREGATION;
        auto* cmd = new (std::nothrow) CcGenCommand(_info);
        if (!cmd) return E_OUTOFMEMORY;
        HRESULT hr = cmd->QueryInterface(riid, ppv);
        cmd->Release();
        return hr;
    }

    STDMETHODIMP LockServer(BOOL lock) override
    {
        lock ? InterlockedIncrement(&g_refCount) : InterlockedDecrement(&g_refCount);
        return S_OK;
    }
};

// ---------------------------------------------------------------------------
// DLL entry points
// ---------------------------------------------------------------------------

BOOL APIENTRY DllMain(HMODULE hModule, DWORD fdwReason, LPVOID)
{
    if (fdwReason == DLL_PROCESS_ATTACH) {
        g_hModule = hModule;
        DisableThreadLibraryCalls(hModule);
    }
    return TRUE;
}

STDAPI DllGetClassObject(REFCLSID clsid, REFIID riid, void** ppv)
{
    if (!ppv) return E_POINTER;
    *ppv = nullptr;
    for (const auto& command : g_commands) {
        if (!IsEqualCLSID(clsid, *command.clsid)) continue;
        IClassFactory* factory = new (std::nothrow) CcGenClassFactory(command);
        if (!factory) return E_OUTOFMEMORY;
        HRESULT hr = factory->QueryInterface(riid, ppv);
        factory->Release();
        return hr;
    }
    return CLASS_E_CLASSNOTAVAILABLE;
}

STDAPI DllCanUnloadNow()
{
    return g_refCount == 0 ? S_OK : S_FALSE;
}
