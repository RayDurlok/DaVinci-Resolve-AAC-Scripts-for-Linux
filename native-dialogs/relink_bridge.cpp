#include "relink_bridge.h"
#include <QCryptographicHash>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QMetaMethod>
#include <QEventLoop>
#include <QTimer>
#include <QRegularExpression>
#include <QElapsedTimer>
#include <cstdio>
#include <cstring>
#include <future>

namespace {
const std::shared_future<bool> &verification()
{
    static const auto result = std::async(std::launch::async, [] {
        QElapsedTimer elapsed;
        elapsed.start();
        QFile executable(QStringLiteral("/proc/self/exe"));
        if (!executable.open(QIODevice::ReadOnly))
            return false;
        QCryptographicHash hash(QCryptographicHash::Sha256);
        const bool valid = hash.addData(&executable) && hash.result().toHex() ==
            "a15c2a3c6b80e46f4a399b987ad5ec5604a0a5445a8e6b27d140c484296d3b77";
        if (qEnvironmentVariable("RESOLVE_RELINK_TIMING") == "1") {
            std::fprintf(stderr, "[relink-timing] background-verification-ms=%lld supported=%d\n",
                         static_cast<long long>(elapsed.elapsed()), valid);
            std::fflush(stderr);
        }
        return valid;
    }).share();
    return result;
}
}

void native_relink::warmVerification()
{
    try {
        (void)verification();
    } catch (...) {
        // Resource exhaustion must not prevent Resolve from starting.
    }
}

bool native_relink::verifiedBuild()
{
    try {
        return verification().get();
    } catch (...) {
        return false;
    }
}

bool SelectionReceipt::attach(QObject *sender, int signalIndex)
{
    return QMetaObject::connect(sender, signalIndex, this, QObject::staticMetaObject.methodCount(),
                               Qt::DirectConnection, nullptr);
}

int SelectionReceipt::qt_metacall(QMetaObject::Call call, int method, void **arguments)
{
    method = QObject::qt_metacall(call, method, arguments);
    if (method < 0)
        return method;
    if (call == QMetaObject::InvokeMetaMethod && method == 0 && arguments[1]) {
        static_assert(sizeof(QString) == 8, "Verified layout requires 64-bit Qt5 QString");
        const auto *entry = static_cast<const char *>(arguments[1]);
        std::memcpy(&id, entry, sizeof(id));
        first = *reinterpret_cast<const QString *>(entry + 8);
        second = *reinterpret_cast<const QString *>(entry + 24);
        received = true;
    }
    return method - 1;
}

int native_relink::finishChoice(QDialog *dialog, QObject *controller, QPushButton *ok,
                               const QString &choice, const QStringList &prefixes)
{
    if (choice.isEmpty()) {
        std::fputs("[relink-bridge] Native picker cancelled; relink cancelled.\n", stderr);
        dialog->reject();
        return QDialog::Rejected;
    }
    const QString folder = QDir::cleanPath(choice);
    const int signalIndex = controller->metaObject()->indexOfSignal(
        "NotifySelectionChanged(MsFolderEntry,MsFolderEntry)");
    const QRegularExpression keyPrefix(QStringLiteral("^[0-9]+:[0-9]+:$"));
    if (prefixes.isEmpty() || signalIndex < 0 || !ok ||
        !QDir::isAbsolutePath(folder) || !QFileInfo(folder).isDir()) {
        dialog->reject();
        return QDialog::Rejected;
    }
    SelectionReceipt receipt;
    if (!receipt.attach(controller, signalIndex)) {
        dialog->reject();
        return QDialog::Rejected;
    }
    QStringList ancestors;
    QString parent = QFileInfo(folder).absolutePath();
    for (int depth = 0; depth < 128; ++depth) {
        ancestors.prepend(parent);
        const QString next = QFileInfo(parent).absolutePath();
        if (next == parent)
            break;
        parent = next;
    }
    bool invoked = false;
    for (const QString &prefix : prefixes) {
        if (!keyPrefix.match(prefix).hasMatch())
            continue;
        // ListFolders only loads children of entries already in the model.
        // Walking ancestors also works when a mounted root is below '/'.
        for (const QString &ancestor : ancestors) {
            QMetaObject::invokeMethod(controller, "ListFolders", Qt::DirectConnection,
                                     Q_ARG(QString, prefix + ancestor));
        }
        QEventLoop settle;
        QTimer::singleShot(100, &settle, &QEventLoop::quit);
        settle.exec(QEventLoop::ExcludeUserInputEvents);
        receipt.received = false;
        invoked = QMetaObject::invokeMethod(controller, "SelectFolder", Qt::DirectConnection,
                                           Q_ARG(QString, prefix + folder));
        if (invoked && receipt.received && receipt.id != -1 && !receipt.first.isEmpty() &&
            QDir::cleanPath(receipt.first) == folder)
            break;
    }
    // The signal also fires for invalid entries. Require the exact physical path,
    // not just an emitted signal, before invoking Resolve's original OK handler.
    if (invoked && receipt.received && receipt.id != -1 && !receipt.first.isEmpty() &&
        QDir::cleanPath(receipt.first) == folder && ok->isEnabled()) {
        ok->click();
        if (dialog->result() == QDialog::Accepted) {
            std::fputs("[relink-entry] Exact folder confirmed; original OK handler accepted.\n", stderr);
            return QDialog::Accepted;
        }
    }
    std::fputs("[relink-entry] No verified acceptance; relink cancelled.\n", stderr);
    dialog->reject();
    return QDialog::Rejected;
}
