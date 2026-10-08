#include "deliver_bridge.h"
#include <QApplication>
#include <QFileInfo>
#include <QProcess>
#include <QProcessEnvironment>
#include <cstdio>

bool native_deliver::openPicker(QDialog *dialog)
{
    if (dialog->windowTitle() != QStringLiteral("File Destination") || dialog->isVisible() ||
        dialog->testAttribute(Qt::WA_DeleteOnClose))
        return false;
    const QString helper = qEnvironmentVariable("RESOLVE_NATIVE_DELIVER_HELPER");
    const QString python = qEnvironmentVariable("RESOLVE_NATIVE_DELIVER_PYTHON");
    if (!QFileInfo(helper).isFile() || !QFileInfo(python).isExecutable())
        return false;

    // Keep at most one native picker for this Resolve process. The Python helper
    // also holds a lock so another invocation cannot create a duplicate picker.
    static QProcess *picker = nullptr;
    if (picker && picker->state() != QProcess::NotRunning) {
        dialog->reject();
        return true;
    }
    if (!picker)
        picker = new QProcess(qApp);
    auto environment = QProcessEnvironment::systemEnvironment();
    // Resolve's bundled Qt/GLib and our preload must not leak into system Python
    // or KDE fallback programs. Communication uses the existing scripting API.
    for (const char *name : {"LD_PRELOAD", "LD_LIBRARY_PATH", "QT_PLUGIN_PATH",
                             "QT_QPA_PLATFORMTHEME", "PYTHONHOME", "PYTHONPATH"})
        environment.remove(QString::fromLatin1(name));
    picker->setProcessEnvironment(environment);
    picker->setProcessChannelMode(QProcess::ForwardedChannels);
    picker->setProgram(python);
    picker->setArguments({helper, "--deliver"});
    picker->start();
    if (!picker->waitForStarted(1000)) {
        std::fputs("[deliver-bridge] Picker helper failed to start; original dialog retained.\n", stderr);
        return false;
    }
    dialog->reject();
    std::fputs("[deliver-bridge] Native picker started before original dialog was shown.\n", stderr);
    std::fflush(stderr);
    return true;
}
