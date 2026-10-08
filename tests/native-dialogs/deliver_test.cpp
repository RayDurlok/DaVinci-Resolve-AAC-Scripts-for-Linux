#include "deliver_bridge.h"
#include <QApplication>
#include <QFile>
#include <QDir>
#include <QTemporaryDir>
#include <QEventLoop>
#include <QTimer>
#include <cstdio>

int main(int argc, char **argv)
{
    QApplication app(argc, argv);
    QTemporaryDir temporary;
    if (!temporary.isValid())
        return 1;
    const QByteArray output = (temporary.path() + "/result").toUtf8();
    qputenv("DELIVER_TEST_OUTPUT", output);
    const QString helper = QCoreApplication::applicationDirPath() + "/deliver_test_helper.py";
    qputenv("RESOLVE_NATIVE_DELIVER_HELPER", helper.toUtf8());
    qputenv("RESOLVE_NATIVE_DELIVER_PYTHON", "/usr/bin/python3");
    QDialog wrong;
    wrong.setWindowTitle("Another dialog");
    if (native_deliver::openPicker(&wrong))
        return 2;
    QDialog dialog;
    dialog.setWindowTitle("File Destination");
    dialog.setAttribute(Qt::WA_DeleteOnClose);
    if (native_deliver::openPicker(&dialog))
        return 3;
    dialog.setAttribute(Qt::WA_DeleteOnClose, false);
    qputenv("RESOLVE_NATIVE_DELIVER_HELPER", "/nonexistent-deliver-helper");
    if (native_deliver::openPicker(&dialog))
        return 4;
    qputenv("RESOLVE_NATIVE_DELIVER_HELPER", helper.toUtf8());
    for (const char *name : {"LD_PRELOAD", "LD_LIBRARY_PATH", "QT_PLUGIN_PATH",
                             "QT_QPA_PLATFORMTHEME", "PYTHONHOME", "PYTHONPATH"})
        qputenv(name, "must-not-reach-helper");
    if (!native_deliver::openPicker(&dialog) || dialog.isVisible() ||
        dialog.result() != QDialog::Rejected)
        return 5;
    QDialog second;
    second.setWindowTitle("File Destination");
    if (!native_deliver::openPicker(&second) || second.isVisible())
        return 6;
    QEventLoop loop;
    QTimer::singleShot(1500, &loop, &QEventLoop::quit);
    loop.exec();
    QFile result(QString::fromUtf8(output));
    if (!result.open(QIODevice::ReadOnly) || result.readAll() != "clean\n")
        return 7;
    std::puts("Hidden handoff, duplicate suppression, environment and fallback checks: PASS");
}
