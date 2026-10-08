#include "relink_bridge.h"
#include "deliver_bridge.h"
#include <QApplication>
#include <QDir>
#include <QFileDialog>
#include <QFileInfo>
#include <QMap>
#include <cstdio>
#include <cstdlib>
#include <dlfcn.h>

namespace {
QObject *folderController(QDialog *dialog)
{
    if (QByteArray(dialog->metaObject()->className()) != "UiFileBrowserImp")
        return nullptr;
    QObject *match = nullptr;
    for (QObject *child : dialog->findChildren<QObject *>()) {
        if (QByteArray(child->metaObject()->className()) != "UiMediaStorageFileBrowserController")
            continue;
        if (match || child->metaObject()->indexOfMethod("SelectFolder(QString)") < 0 ||
            child->metaObject()->indexOfMethod("ListFolders(QString)") < 0)
            return nullptr;
        match = child;
    }
    return match;
}

bool enabled()
{
    return qEnvironmentVariable("RESOLVE_TOOLKIT_NATIVE_DIALOGS") == "1";
}
}

int QApplication::exec()
{
    using Original = int (*)();
    static const auto original = reinterpret_cast<Original>(dlsym(RTLD_NEXT, "_ZN12QApplication4execEv"));
    if (!original)
        std::abort();
    if (enabled())
        native_relink::warmVerification();
    return original();
}

int QDialog::exec()
{
    using Original = int (*)(QDialog *);
    static const auto original = reinterpret_cast<Original>(dlsym(RTLD_NEXT, "_ZN7QDialog4execEv"));
    if (!original)
        std::abort();
    const QString title = windowTitle();
    if (!enabled() || (title != QStringLiteral("Select Source Folder") &&
                       title != QStringLiteral("File Destination")) ||
        !native_relink::verifiedBuild())
        return original(this);
    if (title == QStringLiteral("File Destination"))
        return native_deliver::openPicker(this) ? QDialog::Rejected : original(this);

    QObject *controller = folderController(this);
    auto *ok = findChild<QPushButton *>(QStringLiteral("buttonOk"));
    if (!controller || !ok || testAttribute(Qt::WA_DeleteOnClose) || isVisible())
        return original(this);

    // These offsets were inspected in the exact executable checked above.
    // No private memory access is permitted before that check completes.
    const auto &currentKey = *reinterpret_cast<const QString *>(
        reinterpret_cast<const char *>(controller) + 0x160);
    const int pathStart = currentKey.indexOf('/');
    QStringList prefixes;
    if (pathStart > 0)
        prefixes.append(currentKey.left(pathStart));
    const auto &volumes = *reinterpret_cast<const QMap<QString, void *> *>(
        reinterpret_cast<const char *>(controller) + 0x30);
    for (auto it = volumes.cbegin(); it != volumes.cend(); ++it) {
        const QString key = it.key();
        const int slash = key.indexOf('/');
        prefixes.append(slash < 0 ? key : key.left(slash));
    }
    prefixes.removeDuplicates();
    if (prefixes.isEmpty())
        return original(this);
    const QString initial = pathStart >= 0 && QFileInfo(currentKey.mid(pathStart)).isDir()
        ? currentKey.mid(pathStart) : QDir::homePath();
    const QString folder = QFileDialog::getExistingDirectory(
        parentWidget(), QStringLiteral("Relink source folder"), initial,
        QFileDialog::ShowDirsOnly | QFileDialog::DontResolveSymlinks);
    const int result = native_relink::finishChoice(this, controller, ok, folder, prefixes);
    if (!folder.isEmpty() && result != QDialog::Accepted) {
        std::fputs("[relink-bridge] Using original folder dialog.\n", stderr);
        return original(this);
    }
    return result;
}
