#include <cstdlib>
#include <dlfcn.h>
#include <string>

namespace {
// Keep the bridge loaded here, but never preload Resolve's Qt into child tools.
__attribute__((constructor)) void isolatePreload()
{
    const char *preload = std::getenv("LD_PRELOAD");
    Dl_info self{};
    if (!preload || !dladdr(reinterpret_cast<void *>(&isolatePreload), &self) ||
        !self.dli_fname)
        return;

    const std::string original(preload);
    std::string remaining;
    bool removed = false;
    const char *separators = " :\t\n\r";
    for (std::size_t start = original.find_first_not_of(separators);
         start != std::string::npos;) {
        const auto end = original.find_first_of(separators, start);
        const auto entry = original.substr(start, end - start);
        if (entry == self.dli_fname) {
            removed = true;
        } else {
            if (!remaining.empty())
                remaining += ' ';
            remaining += entry;
        }
        start = end == std::string::npos ? end : original.find_first_not_of(separators, end);
    }
    if (!removed)
        return;
    if (remaining.empty())
        unsetenv("LD_PRELOAD");
    else
        setenv("LD_PRELOAD", remaining.c_str(), 1);
}
}
