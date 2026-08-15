#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <winhttp.h>

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

#define TEXT_CAPACITY 1024
#define CONFIG_CAPACITY 128

typedef void *(__cdecl *create_fn)(const wchar_t *, const wchar_t *,
                                   const wchar_t *, const wchar_t *,
                                   const wchar_t *, uint64_t);
typedef bool(__cdecl *destroy_fn)(void *);
typedef void(__cdecl *execute_fn)(void *);
typedef int(__cdecl *get_error_fn)(void *);
typedef bool(__cdecl *is_end_fn)(void *);
typedef uint32_t(__cdecl *get_user_id_fn)(void *);
typedef const char *(__cdecl *get_token_fn)(void *);
typedef HINTERNET(WINAPI *winhttp_open_request_fn)(
    HINTERNET, LPCWSTR, LPCWSTR, LPCWSTR, LPCWSTR, LPCWSTR const *, DWORD);

static winhttp_open_request_fn original_winhttp_open_request = NULL;

static HINTERNET WINAPI compatible_winhttp_open_request(
    HINTERNET connect, LPCWSTR verb, LPCWSTR object_name, LPCWSTR version,
    LPCWSTR referrer, LPCWSTR const *accept_types, DWORD flags) {
    if (version && wcscmp(version, L"1.1") == 0) {
        version = NULL;
    }
    return original_winhttp_open_request(
        connect, verb, object_name, version, referrer, accept_types, flags);
}

static bool running_under_wine(void) {
    HMODULE ntdll = GetModuleHandleW(L"ntdll.dll");
    return ntdll && GetProcAddress(ntdll, "wine_get_version") != NULL;
}

static bool install_wine_winhttp_compatibility(HMODULE module) {
    if (!running_under_wine()) {
        return true;
    }

    unsigned char *base = (unsigned char *)module;
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)base;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) {
        SetLastError(ERROR_BAD_EXE_FORMAT);
        return false;
    }
    IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE ||
        nt->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR64_MAGIC) {
        SetLastError(ERROR_BAD_EXE_FORMAT);
        return false;
    }

    IMAGE_DATA_DIRECTORY directory =
        nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (!directory.VirtualAddress) {
        SetLastError(ERROR_PROC_NOT_FOUND);
        return false;
    }

    IMAGE_IMPORT_DESCRIPTOR *descriptor =
        (IMAGE_IMPORT_DESCRIPTOR *)(base + directory.VirtualAddress);
    for (; descriptor->Name; ++descriptor) {
        const char *dll_name = (const char *)(base + descriptor->Name);
        if (_stricmp(dll_name, "WINHTTP.dll") != 0) {
            continue;
        }

        IMAGE_THUNK_DATA64 *names = (IMAGE_THUNK_DATA64 *)(
            base + (descriptor->OriginalFirstThunk
                        ? descriptor->OriginalFirstThunk
                        : descriptor->FirstThunk));
        IMAGE_THUNK_DATA64 *functions =
            (IMAGE_THUNK_DATA64 *)(base + descriptor->FirstThunk);
        for (; names->u1.AddressOfData; ++names, ++functions) {
            if (IMAGE_SNAP_BY_ORDINAL64(names->u1.Ordinal)) {
                continue;
            }
            IMAGE_IMPORT_BY_NAME *import =
                (IMAGE_IMPORT_BY_NAME *)(base + names->u1.AddressOfData);
            if (strcmp((const char *)import->Name, "WinHttpOpenRequest") != 0) {
                continue;
            }

            ULONGLONG original_address = functions->u1.Function;
            memcpy(&original_winhttp_open_request, &original_address,
                   sizeof(original_winhttp_open_request));
            if (!original_winhttp_open_request) {
                SetLastError(ERROR_PROC_NOT_FOUND);
                return false;
            }

            winhttp_open_request_fn replacement_function =
                compatible_winhttp_open_request;
            ULONGLONG replacement_address = 0;
            memcpy(&replacement_address, &replacement_function,
                   sizeof(replacement_function));

            DWORD old_protection = 0;
            if (!VirtualProtect(&functions->u1.Function,
                                sizeof(functions->u1.Function),
                                PAGE_READWRITE, &old_protection)) {
                return false;
            }
            functions->u1.Function = replacement_address;
            DWORD ignored = 0;
            VirtualProtect(&functions->u1.Function,
                           sizeof(functions->u1.Function), old_protection,
                           &ignored);
            FlushInstructionCache(GetCurrentProcess(),
                                  &functions->u1.Function,
                                  sizeof(functions->u1.Function));
            return true;
        }
    }

    SetLastError(ERROR_PROC_NOT_FOUND);
    return false;
}

typedef struct {
    create_fn create;
    destroy_fn destroy;
    execute_fn execute;
    get_error_fn get_error;
    is_end_fn is_end;
    get_user_id_fn get_user_id;
    get_token_fn get_token;
} api_t;

static void json_string(const char *value) {
    putchar('"');
    for (const unsigned char *cursor = (const unsigned char *)value; *cursor;
         ++cursor) {
        if (*cursor == '"' || *cursor == '\\') {
            putchar('\\');
            putchar(*cursor);
        } else if (*cursor >= 0x20) {
            putchar(*cursor);
        }
    }
    putchar('"');
}

static int fail(const char *stage, unsigned long error_id, int exit_code) {
    fputs("{\"protocol\":1,\"ok\":false,\"stage\":", stdout);
    json_string(stage);
    printf(",\"error_id\":%lu}\n", error_id);
    return exit_code;
}

static bool read_line(char *buffer, size_t capacity) {
    if (!fgets(buffer, (int)capacity, stdin)) {
        return false;
    }
    buffer[strcspn(buffer, "\r\n")] = '\0';
    return true;
}

static bool utf8_to_wide(const char *source, wchar_t *target,
                         size_t target_capacity) {
    return MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, source, -1,
                               target, (int)target_capacity) != 0;
}

static bool valid_sgid(const char *sgid, const char *qr_game_id) {
    size_t sgid_length = strlen(sgid);
    size_t game_id_length = strlen(qr_game_id);
    if (sgid_length <= 20 || game_id_length != 4 ||
        strncmp(sgid, "SGWC", 4) != 0 ||
        strncmp(sgid + 4, qr_game_id, 4) != 0) {
        return false;
    }
    for (size_t index = 8; index < 20; ++index) {
        if (sgid[index] < '0' || sgid[index] > '9') {
            return false;
        }
    }
    return true;
}

static bool load_api(HMODULE module, api_t *api) {
#define LOAD(name, field)                                                      \
    do {                                                                       \
        FARPROC procedure = GetProcAddress(module, name);                      \
        if (!procedure) {                                                      \
            return false;                                                      \
        }                                                                      \
        memcpy(&api->field, &procedure, sizeof(api->field));                   \
    } while (0)

    LOAD("CCommGetUserData_Create", create);
    LOAD("CCommGetUserData_Destroy", destroy);
    LOAD("CCommGetUserData_execute", execute);
    LOAD("CCommGetUserData_getErrorID", get_error);
    LOAD("CCommGetUserData_isEnd", is_end);
    LOAD("CCommGetUserData_getUserID", get_user_id);
    LOAD("CCommGetUserData_getToken", get_token);
#undef LOAD
    return true;
}

int main(int argc, char **argv) {
    HMODULE module = LoadLibraryW(L"core.dat");
    if (!module) {
        return fail("dll_load", GetLastError(), 10);
    }

    if (!install_wine_winhttp_compatibility(module)) {
        unsigned long error_id = GetLastError();
        FreeLibrary(module);
        return fail("winhttp_hook", error_id, 12);
    }

    api_t api = {0};
    if (!load_api(module, &api)) {
        unsigned long error_id = GetLastError();
        FreeLibrary(module);
        return fail("dll_exports", error_id, 11);
    }

    if (argc > 1 && strcmp(argv[1], "--probe") == 0) {
        puts("{\"protocol\":1,\"ok\":true,\"stage\":\"dll_exports\"}");
        FreeLibrary(module);
        return 0;
    }

    char sgid[TEXT_CAPACITY] = {0};
    char game_id[CONFIG_CAPACITY] = {0};
    char qr_game_id[CONFIG_CAPACITY] = {0};
    char chip_id[CONFIG_CAPACITY] = {0};
    char common_key[CONFIG_CAPACITY] = {0};
    char title_key[CONFIG_CAPACITY] = {0};
    char server_index_text[CONFIG_CAPACITY] = {0};
    char timeout_text[CONFIG_CAPACITY] = {0};
    if (!read_line(sgid, sizeof(sgid)) ||
        !read_line(game_id, sizeof(game_id)) ||
        !read_line(qr_game_id, sizeof(qr_game_id)) ||
        !read_line(chip_id, sizeof(chip_id)) ||
        !read_line(common_key, sizeof(common_key)) ||
        !read_line(title_key, sizeof(title_key)) ||
        !read_line(server_index_text, sizeof(server_index_text)) ||
        !read_line(timeout_text, sizeof(timeout_text))) {
        FreeLibrary(module);
        return fail("input", 0, 20);
    }
    if (!valid_sgid(sgid, qr_game_id)) {
        FreeLibrary(module);
        return fail("sgid", 0, 21);
    }

    wchar_t game_id_w[CONFIG_CAPACITY] = {0};
    wchar_t chip_id_w[CONFIG_CAPACITY] = {0};
    wchar_t common_key_w[CONFIG_CAPACITY] = {0};
    wchar_t qr_data_w[TEXT_CAPACITY] = {0};
    wchar_t title_key_w[CONFIG_CAPACITY] = {0};
    if (!utf8_to_wide(game_id, game_id_w, CONFIG_CAPACITY) ||
        !utf8_to_wide(chip_id, chip_id_w, CONFIG_CAPACITY) ||
        !utf8_to_wide(common_key, common_key_w, CONFIG_CAPACITY) ||
        !utf8_to_wide(sgid + 20, qr_data_w, TEXT_CAPACITY) ||
        !utf8_to_wide(title_key, title_key_w, CONFIG_CAPACITY)) {
        unsigned long error_id = GetLastError();
        FreeLibrary(module);
        return fail("utf8", error_id, 22);
    }

    uint64_t server_index = strtoull(server_index_text, NULL, 10);
    unsigned long timeout_ms = strtoul(timeout_text, NULL, 10);
    if (timeout_ms < 1000UL) {
        timeout_ms = 1000UL;
    } else if (timeout_ms > 120000UL) {
        timeout_ms = 120000UL;
    }

    void *handle = api.create(game_id_w, chip_id_w, common_key_w, qr_data_w,
                              title_key_w, server_index);
    if (!handle) {
        FreeLibrary(module);
        return fail("session_create", 0, 30);
    }

    DWORD started = GetTickCount();
    while (!api.is_end(handle)) {
        api.execute(handle);
        if ((DWORD)(GetTickCount() - started) >= (DWORD)timeout_ms) {
            api.destroy(handle);
            FreeLibrary(module);
            return fail("session_timeout", 0, 31);
        }
        Sleep(50);
    }

    int error_id = api.get_error(handle);
    uint32_t user_id = api.get_user_id(handle);
    const char *token = api.get_token(handle);
    if (!token) {
        token = "";
    }

    bool ok = error_id == 0 && user_id != 0 && token[0] != '\0';
    printf("{\"protocol\":1,\"ok\":%s,\"stage\":\"session\",\"error_id\":%d,"
           "\"user_id\":%lu,\"token\":",
           ok ? "true" : "false", error_id, (unsigned long)user_id);
    json_string(token);
    puts("}");

    api.destroy(handle);
    FreeLibrary(module);
    return ok ? 0 : 32;
}
