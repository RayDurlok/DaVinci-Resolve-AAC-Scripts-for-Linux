#include "relink_bridge.h"
#include <QCoreApplication>
#include <future>
#include <cstdio>

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    native_relink::warmVerification();
    auto first = std::async(std::launch::async, native_relink::verifiedBuild);
    auto second = std::async(std::launch::async, native_relink::verifiedBuild);
    // This test executable is not the supported Resolve binary. Concurrent and
    // repeated requests must all reject it, even after warming the shared result.
    if (first.get() || second.get() || native_relink::verifiedBuild())
        return 1;
    std::puts("Concurrent and cached unsupported-build checks: PASS");
}
