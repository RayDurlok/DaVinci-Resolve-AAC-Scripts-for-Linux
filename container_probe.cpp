#include "container_probe.h"

#include <cassert>
#include <cstring>
#include <string>

const uint8_t ContainerProbe::s_UUID[] = { 0x42, 0xa1, 0x11, 0xfa, 0xaa, 0x1e, 0x45, 0xc9,
                                           0x8a, 0x1e, 0x12, 0x63, 0x58, 0xee, 0x63, 0xe0 };

namespace
{
    void LogOptionalString(IPropertyProvider* p_pProps, PropertyID p_ID, const char* p_pLabel)
    {
        std::string value;
        if (p_pProps->GetString(p_ID, value))
        {
            g_Log(logLevelWarn, "AAC Container Probe :: %s=%s", p_pLabel, value.c_str());
        }
    }

    void LogOptionalUINT32(IPropertyProvider* p_pProps, PropertyID p_ID, const char* p_pLabel)
    {
        uint32_t value = 0;
        if (p_pProps->GetUINT32(p_ID, value))
        {
            g_Log(logLevelWarn, "AAC Container Probe :: %s=%u", p_pLabel, value);
        }
    }
}

class ContainerProbeTrack : public IPluginTrackBase, public IPluginTrackWriter
{
public:
    explicit ContainerProbeTrack(ContainerProbe* p_pContainer)
        : IPluginTrackBase(p_pContainer)
    {
    }

    virtual StatusCode DoWrite(HostBufferRef* p_pBuf) override
    {
        if (p_pBuf == nullptr)
        {
            g_Log(logLevelWarn, "AAC Container Probe :: DoWrite flush");
            return errNone;
        }

        char* pBuffer = nullptr;
        size_t bufferSize = 0;
        if (p_pBuf->LockBuffer(&pBuffer, &bufferSize))
        {
            g_Log(logLevelWarn, "AAC Container Probe :: DoWrite bytes=%llu",
                  static_cast<unsigned long long>(bufferSize));
            p_pBuf->UnlockBuffer();
        }

        return errNone;
    }
};

ContainerProbe::ContainerProbe() = default;

ContainerProbe::~ContainerProbe()
{
    DoClose();
}

StatusCode ContainerProbe::s_Register(HostListRef* p_pList)
{
    const char* extensions[] = {"mp4", "m4a", "mov", "aac"};
    for (size_t i = 0; i < sizeof(extensions) / sizeof(extensions[0]); ++i)
    {
        HostPropertyCollectionRef containerInfo;
        if (!containerInfo.IsValid())
        {
            return errAlloc;
        }

        containerInfo.SetProperty(pIOPropUUID, propTypeUInt8, ContainerProbe::s_UUID, 16);

        const char* pContainerName = "AAC Container Probe";
        containerInfo.SetProperty(pIOPropName, propTypeString, pContainerName, strlen(pContainerName));

        const uint32_t mediaType = (mediaAudio | mediaVideo);
        containerInfo.SetProperty(pIOPropMediaType, propTypeUInt32, &mediaType, 1);

        containerInfo.SetProperty(pIOPropContainerExt, propTypeString, extensions[i], strlen(extensions[i]));

        if (!p_pList->Append(&containerInfo))
        {
            return errFail;
        }

        g_Log(logLevelWarn, "AAC Container Probe :: registered container ext=%s", extensions[i]);
    }

    return errNone;
}

StatusCode ContainerProbe::DoInit(HostPropertyCollectionRef* p_pProps)
{
    g_Log(logLevelWarn, "AAC Container Probe :: DoInit");
    LogOptionalString(p_pProps, pIOPropPath, "path");
    LogOptionalString(p_pProps, pIOPropContainerExt, "containerExt");
    return errNone;
}

StatusCode ContainerProbe::DoOpen(HostPropertyCollectionRef* p_pProps)
{
    g_Log(logLevelWarn, "AAC Container Probe :: DoOpen");
    LogOptionalString(p_pProps, pIOPropPath, "path");
    LogOptionalString(p_pProps, pIOPropContainerExt, "containerExt");
    return errNone;
}

StatusCode ContainerProbe::DoAddTrack(HostPropertyCollectionRef* p_pProps, HostPropertyCollectionRef* p_pCodecProps, IPluginTrackBase** p_pTrack)
{
    g_Log(logLevelWarn, "AAC Container Probe :: DoAddTrack");
    LogOptionalUINT32(p_pProps, pIOPropMediaType, "track.mediaType");
    LogOptionalString(p_pProps, pIOPropName, "track.name");
    LogOptionalUINT32(p_pCodecProps, pIOPropFourCC, "codec.fourcc");

    ContainerProbeTrack* pTrack = new ContainerProbeTrack(this);
    pTrack->Retain();
    m_tracks.push_back(pTrack);
    *p_pTrack = pTrack;

    return errNone;
}

StatusCode ContainerProbe::DoClose()
{
    if (!m_tracks.empty())
    {
        g_Log(logLevelWarn, "AAC Container Probe :: DoClose tracks=%llu",
              static_cast<unsigned long long>(m_tracks.size()));
    }

    for (size_t i = 0; i < m_tracks.size(); ++i)
    {
        m_tracks[i]->Release();
    }
    m_tracks.clear();

    return errNone;
}
