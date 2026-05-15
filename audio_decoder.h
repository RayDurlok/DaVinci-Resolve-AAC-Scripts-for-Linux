#pragma once

#include "wrapper/plugin_api.h"

#include <cstdint>

using namespace IOPlugin;

class AudioDecoder : public IPluginCodecRef
{
public:
    static const uint8_t s_UUID[];
    static const uint8_t s_MP4A_UUID[];
    static const uint8_t s_AAC_UPPER_UUID[];
    static const uint8_t s_ZERO_TAG_UUID[];
    static const uint8_t s_MP4A_LE_UUID[];
    static const uint8_t s_AAC_LE_UUID[];
    static const uint8_t s_AAC_UPPER_LE_UUID[];
    static const uint8_t s_AVC1_UUID[];
    static const uint8_t s_H264_UUID[];
    static const uint8_t s_AVC1_LE_UUID[];
    static const uint8_t s_H264_LE_UUID[];

public:
    AudioDecoder();
    ~AudioDecoder();

    static StatusCode s_RegisterCodecs(HostListRef* p_pList);
    static bool s_IsUUID(const uint8_t* p_pUUID);

protected:
    virtual void DoFlush() override;
    virtual StatusCode DoInit(HostPropertyCollectionRef* p_pProps) override;
    virtual StatusCode DoOpen(HostBufferRef* p_pBuff) override;
    virtual StatusCode DoProcess(HostBufferRef* p_pBuff) override;

private:
    uint64_t m_processCallCount = 0;
    uint32_t m_samplingRate = 0;
    uint32_t m_numChannels = 0;
    uint32_t m_outputBitDepth = 16;
};
