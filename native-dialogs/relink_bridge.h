#pragma once
#include <QDialog>
#include <QObject>
#include <QPushButton>
#include <QString>
#include <QStringList>
#include <cstdint>

// Private Qt layout is enabled only for a SHA-256-verified executable.
class SelectionReceipt : public QObject {
public:
    bool received = false;
    std::int64_t id = -1;
    QString first;
    QString second;
    bool attach(QObject *sender, int signalIndex);
    int qt_metacall(QMetaObject::Call call, int method, void **arguments) override;
};

namespace native_relink {
void warmVerification();
bool verifiedBuild();
int finishChoice(QDialog *dialog, QObject *controller, QPushButton *ok, const QString &choice,
                 const QStringList &prefixes);
}
