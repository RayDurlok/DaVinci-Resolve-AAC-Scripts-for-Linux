#include "audio_decoder.h"

#include <cstring>
#include <string>
#include <vector>

// NOTE: Probe UUID for the AAC decoder object. Generate a new UUID before publishing.
const uint8_t AudioDecoder::s_UUID[] = { 0x7c, 0x81, 0x5a, 0x9b, 0x95, 0x88, 0x4d, 0xe8,
                                         0x9c, 0x2e, 0x5b, 0x42, 0x85, 0x4a, 0x42, 0x31 };

// NOTE: Probe UUID for AAC carried as MPEG-4 Audio sample entries (`mp4a`).
const uint8_t AudioDecoder::s_MP4A_UUID[] = { 0x0b, 0x4b, 0x1a, 0x74, 0x43, 0x6f, 0x4f, 0x35,
                                              0x99, 0x51, 0x1d, 0x56, 0x29, 0x2a, 0x90, 0xd1 };

// NOTE: Probe UUID for hosts that use upper-case AAC FourCC variants.
const uint8_t AudioDecoder::s_AAC_UPPER_UUID[] = { 0xa8, 0xfb, 0x6f, 0x6a, 0x14, 0x24, 0x4f, 0x4c,
                                                   0x9e, 0x62, 0xe6, 0xa6, 0xa5, 0x3f, 0x2f, 0x17 };

// NOTE: Probe UUID for raw AAC/ADTS import paths with no codec tag.
const uint8_t AudioDecoder::s_ZERO_TAG_UUID[] = { 0x0a, 0x7e, 0xe4, 0x65, 0x10, 0x0b, 0x4b, 0x4d,
                                                  0x8d, 0xa8, 0x2a, 0x42, 0xdf, 0x37, 0xda, 0x2b };

// NOTE: Probe UUIDs for little-endian numeric FourCC values as reported by ffprobe.
const uint8_t AudioDecoder::s_MP4A_LE_UUID[] = { 0x36, 0x0d, 0xb4, 0xf2, 0x3a, 0x62, 0x47, 0x7e,
                                                 0xbf, 0x4a, 0x89, 0xaf, 0x64, 0x62, 0xce, 0x15 };

const uint8_t AudioDecoder::s_AAC_LE_UUID[] = { 0xa7, 0x7a, 0x25, 0x3d, 0xe5, 0x6c, 0x4d, 0xb5,
                                                0x8e, 0x89, 0x82, 0x0d, 0x83, 0xf9, 0x83, 0xe2 };

const uint8_t AudioDecoder::s_AAC_UPPER_LE_UUID[] = { 0xfe, 0xa3, 0x07, 0x52, 0xb2, 0x31, 0x40, 0xee,
                                                      0x81, 0xb8, 0x94, 0x49, 0xa7, 0x98, 0x67, 0x27 };

// Video probe UUIDs. These are intentionally routed to the same logging-only object to
// determine whether Resolve ever asks third-party CodecPlugins to decode imported media.
const uint8_t AudioDecoder::s_AVC1_UUID[] = { 0x49, 0x32, 0x16, 0xce, 0xdb, 0x90, 0x47, 0xce,
                                              0x85, 0xb8, 0xb8, 0x41, 0xd7, 0x9a, 0xf8, 0xb4 };

const uint8_t AudioDecoder::s_H264_UUID[] = { 0x44, 0x2c, 0xfa, 0x29, 0x91, 0x34, 0x44, 0x9b,
                                              0xa8, 0xef, 0x9a, 0x7e, 0xd9, 0x29, 0xfa, 0xe0 };

const uint8_t AudioDecoder::s_AVC1_LE_UUID[] = { 0xb1, 0x37, 0x71, 0x4d, 0x17, 0x53, 0x42, 0xd7,
                                                 0xb2, 0x93, 0xe9, 0x33, 0xf8, 0x2f, 0xc0, 0x52 };

const uint8_t AudioDecoder::s_H264_LE_UUID[] = { 0xe4, 0x6c, 0xa2, 0x30, 0xea, 0x95, 0x40, 0x35,
                                                 0x8f, 0x5e, 0x31, 0x99, 0x79, 0x61, 0xc2, 0x52 };

namespace
{
    std::string FourCCToString(uint32_t p_Value)
    {
        char str[5] = {
            static_cast<char>((p_Value >> 24) & 0xff),
            static_cast<char>((p_Value >> 16) & 0xff),
            static_cast<char>((p_Value >> 8) & 0xff),
            static_cast<char>(p_Value & 0xff),
            '\0',
        };

        return std::string(str);
    }

    std::string FourCCToStringLE(uint32_t p_Value)
    {
        char str[5] = {
            static_cast<char>(p_Value & 0xff),
            static_cast<char>((p_Value >> 8) & 0xff),
            static_cast<char>((p_Value >> 16) & 0xff),
            static_cast<char>((p_Value >> 24) & 0xff),
            '\0',
        };

        return std::string(str);
    }

    void LogOptionalUINT32(IPropertyProvider* p_pProps, PropertyID p_ID, const char* p_pLabel)
    {
        uint32_t value = 0;
        if (p_pProps->GetUINT32(p_ID, value))
        {
            g_Log(logLevelWarn, "AAC Decoder Probe :: %s=%u", p_pLabel, value);
        }
    }

    void LogOptionalINT64(IPropertyProvider* p_pProps, PropertyID p_ID, const char* p_pLabel)
    {
        int64_t value = 0;
        if (p_pProps->GetINT64(p_ID, value))
        {
            g_Log(logLevelWarn, "AAC Decoder Probe :: %s=%lld", p_pLabel, static_cast<long long>(value));
        }
    }

    void LogOptionalString(IPropertyProvider* p_pProps, PropertyID p_ID, const char* p_pLabel)
    {
        std::string value;
        if (p_pProps->GetString(p_ID, value))
        {
            g_Log(logLevelWarn, "AAC Decoder Probe :: %s=%s", p_pLabel, value.c_str());
        }
    }

    void LogOptionalMagicCookie(IPropertyProvider* p_pProps)
    {
        PropertyType propType = propTypeNull;
        const void* pValue = nullptr;
        int numValues = 0;
        if (p_pProps->GetProperty(pIOPropMagicCookie, &propType, &pValue, &numValues) == errNone)
        {
            g_Log(logLevelWarn, "AAC Decoder Probe :: magicCookie type=%d bytes=%d", propType, numValues);
        }

        uint32_t magicCookieType = 0;
        if (p_pProps->GetUINT32(pIOPropMagicCookieType, magicCookieType))
        {
            g_Log(logLevelWarn, "AAC Decoder Probe :: magicCookieType=%s (0x%08x)",
                  FourCCToString(magicCookieType).c_str(), magicCookieType);
        }
    }

    std::string MakeNullSeparatedList(const std::vector<std::string>& p_Items)
    {
        std::string result;
        for (size_t i = 0; i < p_Items.size(); ++i)
        {
            result.append(p_Items[i]);
            if (i + 1 < p_Items.size())
            {
                result.append(1, '\0');
            }
        }

        return result;
    }

    StatusCode RegisterCodecVariant(HostListRef* p_pList, const uint8_t* p_pUUID, uint32_t p_FourCC,
                                    uint32_t p_MediaType, const char* p_pCodecName,
                                    const std::vector<std::string>& p_Containers)
    {
        HostPropertyCollectionRef codecInfo;
        if (!codecInfo.IsValid())
        {
            return errAlloc;
        }

        codecInfo.SetProperty(pIOPropUUID, propTypeUInt8, p_pUUID, 16);
        codecInfo.SetProperty(pIOPropName, propTypeString, p_pCodecName, strlen(p_pCodecName));

        uint32_t val = p_FourCC;
        codecInfo.SetProperty(pIOPropFourCC, propTypeUInt32, &val, 1);

        val = p_MediaType;
        codecInfo.SetProperty(pIOPropMediaType, propTypeUInt32, &val, 1);

        val = dirDecode;
        codecInfo.SetProperty(pIOPropCodecDirection, propTypeUInt32, &val, 1);

        uint8_t threadSafe = 0;
        codecInfo.SetProperty(pIOPropThreadSafe, propTypeUInt8, &threadSafe, 1);

        std::vector<uint32_t> bitDepths({16, 24});
        codecInfo.SetProperty(pIOPropBitDepth, propTypeUInt32, bitDepths.data(), bitDepths.size());

        std::vector<uint32_t> samplingRates({8000, 11025, 12000, 16000, 22050, 24000,
                                             32000, 44100, 48000, 88200, 96000});
        codecInfo.SetProperty(pIOPropSamplingRate, propTypeUInt32, samplingRates.data(), samplingRates.size());

        const std::string containerList = MakeNullSeparatedList(p_Containers);
        codecInfo.SetProperty(pIOPropContainerList, propTypeString, containerList.c_str(), containerList.size());

        StatusCode err = p_pList->Append(&codecInfo) ? errNone : errFail;
        if (err == errNone)
        {
            g_Log(logLevelWarn, "AAC Decoder Probe :: registered variant name=%s mediaType=%u fourccBE=%s fourccLE=%s (0x%08x)",
                  p_pCodecName, p_MediaType, FourCCToString(p_FourCC).c_str(), FourCCToStringLE(p_FourCC).c_str(), p_FourCC);
        }

        return err;
    }
}

AudioDecoder::AudioDecoder() = default;

AudioDecoder::~AudioDecoder() = default;

StatusCode AudioDecoder::s_RegisterCodecs(HostListRef* p_pList)
{
    StatusCode err = RegisterCodecVariant(p_pList, AudioDecoder::s_UUID, 'aac ', mediaAudio,
                                          "AAC ADTS Decode Probe (FFmpeg Plugin)", {"aac"});
    if (err != errNone)
    {
        return err;
    }

    err = RegisterCodecVariant(p_pList, AudioDecoder::s_MP4A_UUID, 'mp4a', mediaAudio,
                               "AAC MP4A Decode Probe (FFmpeg Plugin)", {"m4a", "mp4", "mov", "mkv"});
    if (err != errNone)
    {
        return err;
    }

    err = RegisterCodecVariant(p_pList, AudioDecoder::s_AAC_UPPER_UUID, 'AAC ', mediaAudio,
                               "AAC Uppercase Decode Probe (FFmpeg Plugin)", {"aac", "m4a", "mp4", "mov", "mkv"});
    if (err != errNone)
    {
        return err;
    }

    err = RegisterCodecVariant(p_pList, AudioDecoder::s_ZERO_TAG_UUID, 0, mediaAudio,
                               "AAC Untagged Decode Probe (FFmpeg Plugin)", {"aac", "m4a", "mp4", "mov", "mkv"});
    if (err != errNone)
    {
        return err;
    }

    err = RegisterCodecVariant(p_pList, AudioDecoder::s_MP4A_LE_UUID, 0x6134706d, mediaAudio,
                               "AAC MP4A LE Decode Probe (FFmpeg Plugin)", {"m4a", "mp4", "mov", "mkv"});
    if (err != errNone)
    {
        return err;
    }

    err = RegisterCodecVariant(p_pList, AudioDecoder::s_AAC_LE_UUID, 0x20636161, mediaAudio,
                               "AAC ADTS LE Decode Probe (FFmpeg Plugin)", {"aac"});
    if (err != errNone)
    {
        return err;
    }

    err = RegisterCodecVariant(p_pList, AudioDecoder::s_AAC_UPPER_LE_UUID, 0x20434141, mediaAudio,
                               "AAC Uppercase LE Decode Probe (FFmpeg Plugin)", {"aac", "m4a", "mp4", "mov", "mkv"});
    if (err != errNone)
    {
        return err;
    }

    err = RegisterCodecVariant(p_pList, AudioDecoder::s_AVC1_UUID, 'avc1', mediaVideo,
                               "AVC1 Video Decode Probe (FFmpeg Plugin)", {"mp4", "mov", "mkv"});
    if (err != errNone)
    {
        return err;
    }

    err = RegisterCodecVariant(p_pList, AudioDecoder::s_H264_UUID, 'h264', mediaVideo,
                               "H264 Video Decode Probe (FFmpeg Plugin)", {"mp4", "mov", "mkv"});
    if (err != errNone)
    {
        return err;
    }

    err = RegisterCodecVariant(p_pList, AudioDecoder::s_AVC1_LE_UUID, 0x31637661, mediaVideo,
                               "AVC1 LE Video Decode Probe (FFmpeg Plugin)", {"mp4", "mov", "mkv"});
    if (err != errNone)
    {
        return err;
    }

    err = RegisterCodecVariant(p_pList, AudioDecoder::s_H264_LE_UUID, 0x34363268, mediaVideo,
                               "H264 LE Video Decode Probe (FFmpeg Plugin)", {"mp4", "mov", "mkv"});
    if (err != errNone)
    {
        return err;
    }

    g_Log(logLevelWarn, "AAC Decoder Probe :: registered audio and video decode probes incl BE/LE variants");
    return errNone;
}

bool AudioDecoder::s_IsUUID(const uint8_t* p_pUUID)
{
    return memcmp(p_pUUID, AudioDecoder::s_UUID, 16) == 0 ||
           memcmp(p_pUUID, AudioDecoder::s_MP4A_UUID, 16) == 0 ||
           memcmp(p_pUUID, AudioDecoder::s_AAC_UPPER_UUID, 16) == 0 ||
           memcmp(p_pUUID, AudioDecoder::s_ZERO_TAG_UUID, 16) == 0 ||
           memcmp(p_pUUID, AudioDecoder::s_MP4A_LE_UUID, 16) == 0 ||
           memcmp(p_pUUID, AudioDecoder::s_AAC_LE_UUID, 16) == 0 ||
           memcmp(p_pUUID, AudioDecoder::s_AAC_UPPER_LE_UUID, 16) == 0 ||
           memcmp(p_pUUID, AudioDecoder::s_AVC1_UUID, 16) == 0 ||
           memcmp(p_pUUID, AudioDecoder::s_H264_UUID, 16) == 0 ||
           memcmp(p_pUUID, AudioDecoder::s_AVC1_LE_UUID, 16) == 0 ||
           memcmp(p_pUUID, AudioDecoder::s_H264_LE_UUID, 16) == 0;
}

void AudioDecoder::DoFlush()
{
    g_Log(logLevelWarn, "AAC Decoder Probe :: DoFlush after %llu process calls",
          static_cast<unsigned long long>(m_processCallCount));
    m_processCallCount = 0;
}

StatusCode AudioDecoder::DoInit(HostPropertyCollectionRef* p_pProps)
{
    g_Log(logLevelWarn, "AAC Decoder Probe :: DoInit");

    p_pProps->GetUINT32(pIOPropSamplingRate, m_samplingRate);
    p_pProps->GetUINT32(pIOPropNumChannels, m_numChannels);
    p_pProps->GetUINT32(pIOPropBitDepth, m_outputBitDepth);

    LogOptionalUINT32(p_pProps, pIOPropSamplingRate, "samplingRate");
    LogOptionalUINT32(p_pProps, pIOPropNumChannels, "numChannels");
    LogOptionalUINT32(p_pProps, pIOPropBitDepth, "bitDepth");
    LogOptionalUINT32(p_pProps, pIOPropBitsPerSample, "bitsPerSample");
    LogOptionalUINT32(p_pProps, pIOPropAudioChannelLayout, "audioChannelLayout");
    LogOptionalUINT32(p_pProps, pIOPropWidth, "width");
    LogOptionalUINT32(p_pProps, pIOPropHeight, "height");
    LogOptionalString(p_pProps, pIOPropContainerExt, "containerExt");
    LogOptionalString(p_pProps, pIOPropPath, "path");
    LogOptionalMagicCookie(p_pProps);

    return errNone;
}

StatusCode AudioDecoder::DoOpen(HostBufferRef* p_pBuff)
{
    g_Log(logLevelWarn, "AAC Decoder Probe :: DoOpen");

    LogOptionalUINT32(p_pBuff, pIOPropSamplingRate, "open.samplingRate");
    LogOptionalUINT32(p_pBuff, pIOPropNumChannels, "open.numChannels");
    LogOptionalUINT32(p_pBuff, pIOPropBitDepth, "open.bitDepth");
    LogOptionalMagicCookie(p_pBuff);

    char* pBuffer = nullptr;
    size_t bufferSize = 0;
    if (p_pBuff->LockBuffer(&pBuffer, &bufferSize))
    {
        g_Log(logLevelWarn, "AAC Decoder Probe :: DoOpen bufferSize=%llu",
              static_cast<unsigned long long>(bufferSize));
        p_pBuff->UnlockBuffer();
    }

    return errNone;
}

StatusCode AudioDecoder::DoProcess(HostBufferRef* p_pBuff)
{
    ++m_processCallCount;

    char* pBuffer = nullptr;
    size_t bufferSize = 0;
    if (!p_pBuff->LockBuffer(&pBuffer, &bufferSize))
    {
        g_Log(logLevelWarn, "AAC Decoder Probe :: DoProcess #%llu could not lock input buffer",
              static_cast<unsigned long long>(m_processCallCount));
        return errMoreData;
    }

    g_Log(logLevelWarn, "AAC Decoder Probe :: DoProcess #%llu inputBytes=%llu",
          static_cast<unsigned long long>(m_processCallCount),
          static_cast<unsigned long long>(bufferSize));

    p_pBuff->UnlockBuffer();

    LogOptionalINT64(p_pBuff, pIOPropPTS, "packet.pts");
    LogOptionalINT64(p_pBuff, pIOPropDTS, "packet.dts");
    LogOptionalINT64(p_pBuff, pIOPropDuration, "packet.duration");
    LogOptionalUINT32(p_pBuff, pIOPropSamplingRate, "packet.samplingRate");
    LogOptionalUINT32(p_pBuff, pIOPropNumChannels, "packet.numChannels");

    // This first milestone only proves whether Resolve routes AAC packets to the plugin.
    // Returning errMoreData avoids emitting invalid PCM while the FFmpeg decoder is not wired yet.
    return errMoreData;
}
