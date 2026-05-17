#include "plugin.h"

#include <assert.h>

#include <cstring>

#include "audio_decoder.h"
#include "container_probe.h"
#if ENABLE_AAC_ENCODER
#include "audio_encoder.h"
#endif

// NOTE: When creating a plugin for release, please generate a new Plugin UUID in order to prevent conflicts with other third-party plugins.
static const uint8_t pMyUUID[] = { 0x5d, 0x43, 0xce, 0x60, 0x45, 0x11, 0x4f, 0x58, 0x87, 0xde, 0xf3, 0x02, 0x80, 0x1e, 0x7b, 0xbc };

using namespace IOPlugin;

namespace
{
    void LogUUID(const char* p_pPrefix, const unsigned char* p_pUUID)
    {
        g_Log(logLevelWarn,
              "%s %02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
              p_pPrefix,
              p_pUUID[0], p_pUUID[1], p_pUUID[2], p_pUUID[3],
              p_pUUID[4], p_pUUID[5], p_pUUID[6], p_pUUID[7],
              p_pUUID[8], p_pUUID[9], p_pUUID[10], p_pUUID[11],
              p_pUUID[12], p_pUUID[13], p_pUUID[14], p_pUUID[15]);
    }
}

StatusCode g_HandleGetInfo(HostPropertyCollectionRef* p_pProps)
{
    StatusCode err = p_pProps->SetProperty(pIOPropUUID, propTypeUInt8, pMyUUID, 16);
    if (err == errNone)
    {
        const char* pPluginName = "AAC Codec Probe Plugin";
        err = p_pProps->SetProperty(pIOPropName, propTypeString, pPluginName, strlen(pPluginName));
    }

    return err;
}

StatusCode g_HandleCreateObj(unsigned char* p_pUUID, ObjectRef* p_ppObj)
{
    LogUUID("AAC Decoder Probe :: g_HandleCreateObj requested UUID", p_pUUID);

#if ENABLE_AAC_ENCODER
    if (memcmp(p_pUUID, AudioEncoder::s_UUID, 16) == 0)
    {
        g_Log(logLevelWarn, "AAC Decoder Probe :: creating AudioEncoder object");
        *p_ppObj = new AudioEncoder();
        return errNone;
    }
#endif

    if (AudioDecoder::s_IsUUID(p_pUUID))
    {
        g_Log(logLevelWarn, "AAC Decoder Probe :: creating AudioDecoder object");
        *p_ppObj = new AudioDecoder();
        return errNone;
    }

    if (memcmp(p_pUUID, ContainerProbe::s_UUID, 16) == 0)
    {
        g_Log(logLevelWarn, "AAC Decoder Probe :: creating ContainerProbe object");
        *p_ppObj = new ContainerProbe();
        return errNone;
    }

    return errUnsupported;
}

StatusCode g_HandlePluginStart()
{
    // perform libs initialization if needed
    return errNone;
}

StatusCode g_HandlePluginTerminate()
{
    return errNone;
}

StatusCode g_ListCodecs(HostListRef* p_pList)
{
    // For any optional/new features, please check Host version before using it
    if (GetHostAPI()->version >= 0x00000001)
    {
#if ENABLE_AAC_ENCODER
        StatusCode err = AudioEncoder::s_RegisterCodecs(p_pList);
        if (err != errNone)
        {
            return err;
        }
#endif

        return AudioDecoder::s_RegisterCodecs(p_pList);
    }

    return errNone;
}

StatusCode g_ListContainers(HostListRef* p_pList)
{
    return ContainerProbe::s_Register(p_pList);
}

StatusCode g_GetEncoderSettings(unsigned char* p_pUUID, HostPropertyCollectionRef* p_pValues, HostListRef* p_pSettingsList)
{
#if ENABLE_AAC_ENCODER
    if (memcmp(p_pUUID, AudioEncoder::s_UUID, 16) == 0)
    {
        return AudioEncoder::s_GetEncoderSettings(p_pValues, p_pSettingsList);
    }
#endif

    return errNoCodec;
}
