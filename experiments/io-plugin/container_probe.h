#pragma once

#include "wrapper/plugin_api.h"

#include <vector>

using namespace IOPlugin;

class ContainerProbeTrack;

class ContainerProbe : public IPluginContainerRef
{
public:
    static const uint8_t s_UUID[];

public:
    ContainerProbe();

    static StatusCode s_Register(HostListRef* p_pList);

protected:
    virtual StatusCode DoInit(HostPropertyCollectionRef* p_pProps) override;
    virtual StatusCode DoOpen(HostPropertyCollectionRef* p_pProps) override;
    virtual StatusCode DoAddTrack(HostPropertyCollectionRef* p_pProps, HostPropertyCollectionRef* p_pCodecProps, IPluginTrackBase** p_pTrack) override;
    virtual StatusCode DoClose() override;

protected:
    virtual ~ContainerProbe();

private:
    std::vector<ContainerProbeTrack*> m_tracks;
};
