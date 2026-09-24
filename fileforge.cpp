#include <algorithm>
#include <cctype>
#include <cerrno>
#include <cstdio>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#elif defined(__linux__)
#include <fcntl.h>
#include <sys/syscall.h>
#include <unistd.h>
#endif

namespace fs = std::filesystem;
const char* undoName = ".fileforge_undo.log";

std::string lower(std::string value) {
    for (char& c : value) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return value;
}

std::string category(const fs::path& path) {
    const std::string ext = lower(path.extension().u8string());
    const std::map<std::string, std::vector<std::string>> types = {
        {"Images", {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".heic", ".bmp"}},
        {"Documents", {".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".csv", ".xlsx", ".pptx"}},
        {"Videos", {".mp4", ".mov", ".avi", ".mkv", ".webm"}},
        {"Audio", {".mp3", ".wav", ".flac", ".m4a", ".ogg"}},
        {"Archives", {".zip", ".rar", ".7z", ".tar", ".gz"}},
        {"Code", {".cpp", ".h", ".hpp", ".c", ".java", ".py", ".sql", ".js", ".ts", ".html", ".css"}},
    };
    for (const auto& item : types)
        if (std::find(item.second.begin(), item.second.end(), ext) != item.second.end()) return item.first;
    return "Other";
}

bool excluded(const fs::path& path) {
    const std::string name = lower(path.filename().u8string());
    const std::set<std::string> appFiles = {
        "fileforge", "fileforge.exe", "fileforge.cpp", "fileforge_desktop.py", "desktop.ini", "thumbs.db"
    };
    const std::set<std::string> configExtensions = {
        ".ini", ".cfg", ".conf", ".json", ".yaml", ".yml", ".toml", ".lock"
    };
    return name.empty() || name.front() == '.' || appFiles.count(name) ||
           configExtensions.count(lower(path.extension().u8string()));
}

// Windows stores hidden/system flags separately from a file's name.
bool hiddenBySystem(const fs::path& path) {
#ifdef _WIN32
    const DWORD flags = GetFileAttributesW(path.c_str());
    if (flags == INVALID_FILE_ATTRIBUTES)
        throw std::runtime_error("Cannot inspect Windows file attributes.");
    return (flags & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM)) != 0;
#else
    (void)path;
    return false;
#endif
}

// symlink_status also sees dangling links, which must count as occupied names.
bool occupied(const fs::path& path) {
    std::error_code error;
    const auto status = fs::symlink_status(path, error);
    if (error && error != std::errc::no_such_file_or_directory) throw fs::filesystem_error("Cannot inspect path", path, error);
    return status.type() != fs::file_type::not_found;
}

bool plainFile(const fs::path& path) { return fs::is_regular_file(fs::symlink_status(path)); }

void checkCategoryFolder(const fs::path& path) {
    if (occupied(path) && !fs::is_directory(fs::symlink_status(path)))
        throw std::runtime_error("Category path is not a regular folder: " + path.filename().u8string());
}

std::string sizeText(uintmax_t bytes) {
    std::ostringstream out;
    if (bytes >= 1024 * 1024) out << std::fixed << std::setprecision(1) << bytes / (1024.0 * 1024) << " MB";
    else if (bytes >= 1024) out << std::fixed << std::setprecision(1) << bytes / 1024.0 << " KB";
    else out << bytes << " B";
    return out.str();
}

// Small JSON writer: all file names are escaped, never interpolated as raw JSON.
std::string quote(const std::string& value) {
    std::ostringstream out;
    out << '"';
    for (unsigned char c : value) {
        if (c == '"' || c == '\\') out << '\\' << c;
        else if (c < 32) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << int(c) << std::dec;
        else out << c;
    }
    out << '"';
    return out.str();
}

std::string stringArray(const std::vector<std::string>& items) {
    std::string out = "[";
    for (size_t i = 0; i < items.size(); ++i) out += (i ? "," : "") + quote(items[i]);
    return out + "]";
}

// FNV is a change/corruption check, not an authentication or security hash.
std::string checksum(const std::string& value) {
    uint64_t hash = 14695981039346656037ULL;
    for (unsigned char c : value) { hash ^= c; hash *= 1099511628211ULL; }
    std::ostringstream out;
    out << std::hex << hash;
    return out.str();
}

std::string hexEncode(const std::string& value) {
    const char* digits = "0123456789abcdef";
    std::string out;
    for (unsigned char c : value) { out += digits[c >> 4]; out += digits[c & 15]; }
    return out;
}

std::string hexDecode(const std::string& value) {
    if (value.empty() || value.size() % 2) throw std::runtime_error("Invalid undo record encoding.");
    std::string out;
    for (size_t i = 0; i < value.size(); i += 2) {
        const auto a = std::string("0123456789abcdef").find(value[i]);
        const auto b = std::string("0123456789abcdef").find(value[i + 1]);
        if (a == std::string::npos || b == std::string::npos || (a == 0 && b == 0))
            throw std::runtime_error("Invalid undo record encoding.");
        out += static_cast<char>(a * 16 + b);
    }
    return out;
}

struct File {
    std::string name, type;
    uintmax_t size;
    long long modified;
};

File describe(const fs::path& path) {
    return {path.filename().u8string(), category(path), fs::file_size(path),
            static_cast<long long>(fs::last_write_time(path).time_since_epoch().count())};
}

bool matches(const fs::path& path, const File& file) {
    if (!occupied(path) || !plainFile(path)) return false;
    const File current = describe(path);
    return current.size == file.size && current.modified == file.modified;
}

fs::path collisionSafe(const fs::path& path, const std::set<std::string>& reserved = {}) {
    auto free = [&](const fs::path& candidate) {
        return !occupied(candidate) && !reserved.count(candidate.generic_u8string());
    };
    if (free(path)) return path;
    for (unsigned long long index = 1; index < 1000000; ++index) {
        const auto name = path.stem().u8string() + " (" + std::to_string(index) + ")" + path.extension().u8string();
        const fs::path candidate = path.parent_path() / fs::u8path(name);
        if (free(candidate)) return candidate;
    }
    throw std::runtime_error("Too many filename collisions.");
}

struct Move { File file; std::string destination; };
struct Preview {
    std::vector<File> files;
    std::vector<Move> moves;
    std::vector<std::string> blockers;
    std::map<std::string, int> categories;
    uintmax_t total = 0;
    size_t skipped = 0;
    bool undoAvailable = false;
    std::string snapshot;
};

Preview preview(const fs::path& root) {
    Preview result;
    for (const auto& entry : fs::directory_iterator(root)) {
        if (!fs::is_regular_file(entry.symlink_status()) || excluded(entry.path()) || hiddenBySystem(entry.path())) { ++result.skipped; continue; }
        result.files.push_back(describe(entry.path()));
    }
    std::sort(result.files.begin(), result.files.end(), [](const File& a, const File& b) { return a.name < b.name; });
    std::set<std::string> reserved, checked;
    std::string signature = root.generic_u8string();
    for (const File& file : result.files) {
        ++result.categories[file.type];
        result.total += file.size;
        const fs::path folder = root / file.type;
        if (checked.insert(file.type).second) {
            try { checkCategoryFolder(folder); }
            catch (const std::exception& error) { result.blockers.push_back(error.what()); }
        }
        // A blocked folder has no valid destination to promise in a preview.
        std::string destination;
        if (!occupied(folder) || fs::is_directory(fs::symlink_status(folder))) {
            const fs::path path = collisionSafe(folder / fs::u8path(file.name), reserved);
            reserved.insert(path.generic_u8string());
            destination = path.lexically_relative(root).generic_u8string();
            result.moves.push_back({file, destination});
        }
        signature += "\n" + hexEncode(file.name) + ":" + std::to_string(file.size) + ":" +
                     std::to_string(file.modified) + ":" + hexEncode(destination);
    }
    const fs::path log = root / undoName;
    if (occupied(log)) {
        result.undoAvailable = plainFile(log);
        result.blockers.push_back(result.undoAvailable ? "An undo record exists. Undo the last organization first."
                                                     : "The undo record path is not a regular file.");
    }
    for (const auto& blocker : result.blockers) signature += "\n" + blocker;
    result.snapshot = checksum(signature);
    return result;
}

std::string previewJson(const fs::path& root, const std::string& command, const Preview& result) {
    std::ostringstream out;
    out << "{\"ok\":true,\"command\":" << quote(command) << ",\"folder\":" << quote(root.u8string())
        << ",\"file_count\":" << result.files.size() << ",\"total_bytes\":" << result.total
        << ",\"skipped_count\":" << result.skipped << ",\"undo_available\":" << (result.undoAvailable ? "true" : "false")
        << ",\"snapshot\":" << quote(result.snapshot) << ",\"blockers\":" << stringArray(result.blockers) << ",\"categories\":{";
    bool first = true;
    for (const auto& item : result.categories) { out << (first ? "" : ",") << quote(item.first) << ':' << item.second; first = false; }
    out << "},\"files\":[";
    for (size_t i = 0; i < result.files.size(); ++i) {
        const File& file = result.files[i];
        out << (i ? "," : "") << "{\"name\":" << quote(file.name) << ",\"category\":" << quote(file.type)
            << ",\"size\":" << file.size << ",\"modified\":" << file.modified << '}';
    }
    out << "],\"moves\":[";
    for (size_t i = 0; i < result.moves.size(); ++i) {
        const Move& move = result.moves[i];
        out << (i ? "," : "") << "{\"source\":" << quote(move.file.name) << ",\"destination\":" << quote(move.destination)
            << ",\"category\":" << quote(move.file.type) << ",\"size\":" << move.file.size << '}';
    }
    out << "]}";
    return out.str();
}

// Unlike POSIX rename(), these operations never replace an existing destination.
// The portable fallback creates a hard link before removing the old name.
void moveWithoutOverwrite(const fs::path& source, const fs::path& destination) {
    if (!plainFile(source) || occupied(destination)) throw std::runtime_error("Source or destination changed. Nothing overwritten.");
#ifdef _WIN32
    if (!MoveFileW(source.c_str(), destination.c_str()))
        throw std::runtime_error("Windows could not move this file (it may be open or on another volume).");
#elif defined(__linux__) && defined(SYS_renameat2)
    if (syscall(SYS_renameat2, AT_FDCWD, source.c_str(), AT_FDCWD, destination.c_str(), 1) != 0)
        throw std::runtime_error("Could not move file safely: " + std::error_code(errno, std::generic_category()).message());
#else
    fs::create_hard_link(source, destination);
    fs::remove(source);
#endif
}

// Each flushed line is checksummed. Paths are hex-encoded to support newlines.
class JournalWriter {
    std::FILE* file = nullptr;
public:
    JournalWriter(const fs::path& path, bool create) {
        if (!create && (!occupied(path) || !plainFile(path))) throw std::runtime_error("Unsafe undo record path.");
#ifdef _WIN32
        file = _wfopen(path.c_str(), create ? L"wbx" : L"ab");
#else
        file = std::fopen(path.c_str(), create ? "wbx" : "ab");
#endif
        if (!file) throw std::runtime_error("Cannot write the undo record. Check folder permissions.");
    }
    ~JournalWriter() { if (file) std::fclose(file); }
    JournalWriter(const JournalWriter&) = delete;
    JournalWriter& operator=(const JournalWriter&) = delete;
    void append(const std::string& payload) {
        const std::string line = payload + "|" + checksum(payload) + "\n";
        if (std::fwrite(line.data(), 1, line.size(), file) != line.size() || std::fflush(file) != 0)
            throw std::runtime_error("Undo record write failed. Keep the log and retry Undo.");
    }
};

struct OperationResult {
    size_t count = 0, pending = 0;
    std::vector<std::string> warnings;
};

OperationResult organize(const fs::path& root, const std::string& snapshot) {
    const Preview plan = preview(root);
    if (snapshot.empty() || snapshot != plan.snapshot) throw std::runtime_error("The folder changed since preview. Refresh the preview and try again.");
    if (!plan.blockers.empty()) throw std::runtime_error(plan.blockers.front());
    OperationResult result;
    if (plan.moves.empty()) return result;
    {
        JournalWriter log(root / undoName, true);
        log.append("FILEFORGE 2 " + hexEncode(root.generic_u8string()) + " " + std::to_string(plan.moves.size()));
        for (const auto& move : plan.moves)
            log.append("P " + hexEncode(move.file.name) + " " + hexEncode(move.destination) + " " +
                       std::to_string(move.file.size) + " " + std::to_string(move.file.modified));
        for (size_t index = 0; index < plan.moves.size(); ++index) {
            const Move& move = plan.moves[index];
            try {
                const fs::path source = root / fs::u8path(move.file.name);
                const fs::path destination = root / fs::u8path(move.destination);
                checkCategoryFolder(destination.parent_path());
                if (!matches(source, move.file)) throw std::runtime_error("File changed since preview.");
                fs::create_directory(destination.parent_path());
                moveWithoutOverwrite(source, destination);
                ++result.count;
            } catch (const std::exception& error) {
                result.warnings.push_back(move.file.name + ": " + error.what());
                continue;
            }
            // If this append fails, P still provides recovery for the moved file.
            log.append("D " + std::to_string(index));
        }
    }
    result.pending = plan.moves.size();
    return result;
}

bool singleName(const std::string& name) {
    const fs::path path = fs::u8path(name);
    return !name.empty() && name != "." && name != ".." && !path.has_root_path() && path.filename() == path;
}

bool validCollisionName(const fs::path& candidate, const fs::path& original) {
    if (candidate == original) return true;
    if (candidate.extension() != original.extension()) return false;
    const std::string stem = candidate.stem().u8string();
    const std::string prefix = original.stem().u8string() + " (";
    if (stem.compare(0, prefix.size(), prefix) || stem.size() <= prefix.size() + 1 || stem.back() != ')') return false;
    const std::string number = stem.substr(prefix.size(), stem.size() - prefix.size() - 1);
    return number.front() != '0' && std::all_of(number.begin(), number.end(), [](unsigned char c) { return std::isdigit(c); });
}

struct Recovery { Move move; bool done = false, restored = false; std::string restoreName; };

std::vector<Recovery> readJournal(const fs::path& root) {
    const fs::path path = root / undoName;
    if (!plainFile(path)) throw std::runtime_error("Unsafe undo record: expected a regular file, not a link.");
    if (fs::file_size(path) > 64 * 1024 * 1024) throw std::runtime_error("Undo record is too large to validate safely.");
    std::ifstream input(path, std::ios::binary);
    if (!input) throw std::runtime_error("Cannot read the undo record.");
    std::vector<Recovery> records;
    std::set<std::string> sources, destinations;
    std::string line;
    size_t expected = 0;
    bool header = false, events = false;
    while (std::getline(input, line)) {
        if (input.eof()) throw std::runtime_error("Incomplete undo record. Keep it for manual recovery.");
        const size_t separator = line.rfind('|');
        if (separator == std::string::npos || checksum(line.substr(0, separator)) != line.substr(separator + 1))
            throw std::runtime_error("Invalid undo record checksum. No files moved.");
        std::istringstream fields(line.substr(0, separator));
        std::string kind, extra;
        fields >> kind;
        if (!header) {
            int version = 0;
            std::string folder;
            if (kind != "FILEFORGE" || !(fields >> version >> folder >> expected) || version != 2 || expected > 1000000 ||
                hexDecode(folder) != root.generic_u8string()) throw std::runtime_error("Undo record belongs to another folder or version.");
            header = true;
        } else if (kind == "P") {
            Recovery record;
            std::string source, destination;
            if (events || !(fields >> source >> destination >> record.move.file.size >> record.move.file.modified))
                throw std::runtime_error("Invalid undo entry.");
            record.move.file.name = hexDecode(source);
            record.move.file.type = category(fs::u8path(record.move.file.name));
            record.move.destination = hexDecode(destination);
            const fs::path dest = fs::u8path(record.move.destination);
            if (!singleName(record.move.file.name) || excluded(fs::u8path(record.move.file.name)) ||
                dest.has_root_path() || dest.parent_path() != fs::path(record.move.file.type) ||
                !singleName(dest.filename().u8string()) || !validCollisionName(dest.filename(), fs::u8path(record.move.file.name)) ||
                !sources.insert(record.move.file.name).second || !destinations.insert(record.move.destination).second)
                throw std::runtime_error("Unsafe undo paths. No files moved.");
            records.push_back(record);
        } else {
            events = true;
            size_t index;
            if (records.size() != expected || !(fields >> index) || index >= records.size() || records[index].restored)
                throw std::runtime_error("Invalid undo event.");
            Recovery& record = records[index];
            if (kind == "D" && !record.done && record.restoreName.empty()) record.done = true;
            else if (kind == "R") record.restored = true;
            else if (kind == "U") {
                std::string name;
                if (!(fields >> name)) throw std::runtime_error("Invalid restore entry.");
                record.restoreName = hexDecode(name);
                if (!singleName(record.restoreName) || !validCollisionName(fs::u8path(record.restoreName), fs::u8path(record.move.file.name)))
                    throw std::runtime_error("Unsafe restore name.");
            } else throw std::runtime_error("Invalid undo event type.");
        }
        if (fields >> extra) throw std::runtime_error("Unexpected data in undo record.");
    }
    if (input.bad() || !header || records.size() != expected) throw std::runtime_error("Incomplete undo record. No files moved.");
    // Validate every directory before changing any file, including pending entries.
    for (const auto& record : records) {
        checkCategoryFolder(root / record.move.file.type);
        const fs::path source = root / fs::u8path(record.move.destination);
        if (occupied(source) && !plainFile(source)) throw std::runtime_error("Unsafe file in undo record.");
    }
    return records;
}

OperationResult undo(const fs::path& root) {
    OperationResult result;
    if (!occupied(root / undoName)) return result;
    const auto records = readJournal(root);
    {
        JournalWriter log(root / undoName, false);
        for (size_t index = 0; index < records.size(); ++index) {
            const Recovery& record = records[index];
            if (record.restored) continue;
            const File& file = record.move.file;
            const fs::path source = root / fs::u8path(record.move.destination);
            const fs::path original = root / fs::u8path(file.name);
            bool recovered = false;
            try {
                checkCategoryFolder(source.parent_path());
                if (!record.restoreName.empty()) {
                    const fs::path target = root / fs::u8path(record.restoreName);
                    if (!occupied(source) && matches(target, file)) recovered = true;
                    else if (matches(source, file) && matches(target, file) && fs::equivalent(source, target)) {
                        fs::remove(source); // Interrupted portable hard-link move: original still exists.
                        recovered = true;
                    }
                }
                if (!recovered && !record.done && matches(original, file)) {
                    if (!occupied(source)) recovered = true; // Prepared, but never moved.
                    else if (matches(source, file) && fs::equivalent(source, original)) {
                        fs::remove(source);
                        recovered = true;
                    } else throw std::runtime_error("Unfinished move is ambiguous; keep both files for manual recovery.");
                }
                if (!recovered) {
                    if (!matches(source, file)) throw std::runtime_error("Organized file is missing or changed; entry kept for retry.");
                    const fs::path target = collisionSafe(original);
                    log.append("U " + std::to_string(index) + " " + hexEncode(target.filename().u8string()));
                    moveWithoutOverwrite(source, target);
                    ++result.count;
                }
            } catch (const std::exception& error) {
                ++result.pending;
                result.warnings.push_back(file.name + ": " + error.what());
                continue;
            }
            // A failed append stops processing; the preceding U supports recovery.
            log.append("R " + std::to_string(index));
        }
    }
    if (result.pending == 0) fs::remove(root / undoName);
    return result;
}

bool sameContents(const fs::path& a, const fs::path& b) {
    std::ifstream left(a, std::ios::binary), right(b, std::ios::binary);
    if (!left || !right) throw std::runtime_error("Cannot read a file for duplicate comparison.");
    char l[65536], r[65536];
    do {
        left.read(l, sizeof(l)); right.read(r, sizeof(r));
        if (left.bad() || right.bad()) throw std::runtime_error("Duplicate comparison failed while reading a file.");
        if (left.gcount() != right.gcount() || !std::equal(l, l + left.gcount(), r)) return false;
    } while (left && right);
    return true;
}

std::vector<std::vector<File>> duplicates(const fs::path& root) {
    const Preview state = preview(root);
    std::map<uintmax_t, std::vector<File>> sizes;
    for (const auto& file : state.files) sizes[file.size].push_back(file);
    std::vector<std::vector<File>> result;
    for (const auto& item : sizes) {
        if (item.second.size() < 2) continue;
        std::vector<std::vector<File>> groups;
        for (const auto& file : item.second) {
            bool found = false;
            for (auto& group : groups) {
                if (sameContents(root / fs::u8path(file.name), root / fs::u8path(group.front().name))) {
                    group.push_back(file); found = true; break;
                }
            }
            if (!found) groups.push_back({file});
        }
        for (const auto& group : groups) if (group.size() > 1) result.push_back(group);
    }
    for (const auto& file : state.files)
        if (!matches(root / fs::u8path(file.name), file)) throw std::runtime_error("Folder changed during comparison. Scan again.");
    return result;
}

std::string operationJson(const std::string& command, const OperationResult& result) {
    return "{\"ok\":true,\"command\":" + quote(command) + (command == "undo" ? ",\"restored\":" : ",\"moved\":") +
           std::to_string(result.count) + ",\"pending_count\":" + std::to_string(result.pending) +
           ",\"warnings\":" + stringArray(result.warnings) + "}";
}

fs::path folderPath(const std::string& value) {
    const fs::path input = fs::u8path(value);
    if (value.empty() || !fs::is_directory(input)) throw std::runtime_error("Folder not found. Choose an existing folder.");
    return fs::canonical(input);
}

int jsonMain(const std::vector<std::string>& args) {
    std::string command = args.size() > 2 ? args[2] : "";
    try {
        if (args.size() < 4) throw std::runtime_error("Usage: fileforge --json COMMAND FOLDER [--snapshot TOKEN]");
        const fs::path root = folderPath(args[3]);
        if (command == "organize") {
            if (args.size() != 6 || args[4] != "--snapshot") throw std::runtime_error("Organize requires a preview --snapshot token.");
            std::cout << operationJson(command, organize(root, args[5])) << '\n';
        } else if (args.size() != 4) throw std::runtime_error("Unexpected command arguments.");
        else if (command == "scan" || command == "preview") std::cout << previewJson(root, command, preview(root)) << '\n';
        else if (command == "undo") std::cout << operationJson(command, undo(root)) << '\n';
        else if (command == "duplicates") {
            const auto groups = duplicates(root);
            size_t count = 0;
            uintmax_t bytes = 0;
            std::ostringstream out;
            out << "{\"ok\":true,\"command\":\"duplicates\",\"groups\":[";
            for (size_t i = 0; i < groups.size(); ++i) {
                std::vector<std::string> names;
                for (const auto& file : groups[i]) names.push_back(file.name);
                count += names.size() - 1;
                bytes += (names.size() - 1) * groups[i][0].size;
                out << (i ? "," : "") << "{\"size\":" << groups[i][0].size << ",\"files\":" << stringArray(names) << '}';
            }
            out << "],\"duplicate_count\":" << count << ",\"reclaimable_bytes\":" << bytes << '}';
            std::cout << out.str() << '\n';
        } else throw std::runtime_error("Unknown command. Use scan, preview, organize, duplicates or undo.");
        return 0;
    } catch (const std::exception& error) {
        std::cout << "{\"ok\":false,\"command\":" << quote(command) << ",\"error\":" << quote(error.what()) << "}\n";
        return 1;
    }
}

int interactiveMain() {
    std::cout << "========================================\n FileForge - C++ File Organizer\n========================================\nFolder path: ";
    std::string input;
    std::getline(std::cin, input);
    try {
        const fs::path root = folderPath(input);
        while (true) {
            std::cout << "\n1. Scan folder\n2. Preview destinations\n3. Organize files\n4. Find exact duplicates\n5. Undo last organization\n0. Exit\nChoice: ";
            std::string choice;
            if (!std::getline(std::cin, choice) || choice == "0") break;
            try {
                if (choice == "1" || choice == "2" || choice == "3") {
                    const Preview plan = preview(root);
                    std::cout << '\n' << plan.files.size() << " files - " << sizeText(plan.total) << " - " << plan.skipped << " excluded entries\n";
                    if (choice == "1") {
                        for (const auto& file : plan.files) std::cout << quote(file.name) << "  " << file.type << "  " << sizeText(file.size) << '\n';
                    } else {
                        for (const auto& move : plan.moves) std::cout << quote(move.file.name) << " -> " << quote(move.destination) << '\n';
                        for (const auto& blocker : plan.blockers) std::cout << "Blocked: " << blocker << '\n';
                        if (choice == "3" && !plan.moves.empty() && plan.blockers.empty()) {
                            std::cout << "Organize these files? (y/n): ";
                            std::string yes;
                            std::getline(std::cin, yes);
                            if (yes == "y" || yes == "Y") {
                                const auto result = organize(root, plan.snapshot);
                                std::cout << "Organized " << result.count << " files. Undo is available.\n";
                                for (const auto& warning : result.warnings) std::cout << warning << '\n';
                            }
                        }
                    }
                } else if (choice == "4") {
                    const auto groups = duplicates(root);
                    std::cout << "\nEXACT DUPLICATES (report only)\n";
                    if (groups.empty()) std::cout << "None found.\n";
                    for (const auto& group : groups) {
                        std::cout << sizeText(group.front().size) << ":\n";
                        for (const auto& file : group) std::cout << "  " << quote(file.name) << '\n';
                    }
                } else if (choice == "5") {
                    const auto result = undo(root);
                    std::cout << "Restored " << result.count << " files; " << result.pending << " remain in the undo record.\n";
                    for (const auto& warning : result.warnings) std::cout << warning << '\n';
                } else std::cout << "Choose a number from 0 to 5.\n";
            } catch (const std::exception& error) { std::cerr << "Error: " << error.what() << '\n'; }
        }
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
    return 0;
}

int run(const std::vector<std::string>& args) {
    if (args.size() > 1 && args[1] == "--json") return jsonMain(args);
    if (args.size() > 1) {
        std::cout << "FileForge\n  fileforge                     Interactive CLI\n"
                     "  fileforge --json scan FOLDER\n  fileforge --json preview FOLDER\n"
                     "  fileforge --json organize FOLDER --snapshot TOKEN\n"
                     "  fileforge --json duplicates FOLDER\n  fileforge --json undo FOLDER\n";
        return args[1] == "--help" ? 0 : 1;
    }
    return interactiveMain();
}

#ifdef _WIN32
int wmain(int argc, wchar_t* argv[]) {
    std::vector<std::string> args;
    for (int i = 0; i < argc; ++i) args.push_back(fs::path(argv[i]).u8string());
    return run(args);
}
#else
int main(int argc, char* argv[]) { return run(std::vector<std::string>(argv, argv + argc)); }
#endif
