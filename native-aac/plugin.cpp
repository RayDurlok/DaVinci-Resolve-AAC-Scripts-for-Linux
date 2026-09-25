// Derived from Toxblh/davinci-linux-aac-codec (GPLv3); separate toolkit UUIDs.
#include "plugin.h"

#include <assert.h>

#include <cstring>

#include "audio_encoder.h"

// NOTE: When creating a plugin for release, please generate a new Plugin UUID in order to prevent conflicts with other third-party plugins.
static const uint8_t pMyUUID[] = { 0xf1, 0x82, 0xd3, 0x56, 0x19, 0xbe, 0x43, 0xa2, 0x88, 0x71, 0x6b, 0xfa, 0xda, 0x20, 0x62, 0x09 };

using namespace IOPlugin;

StatusCode g_HandleGetInfo(HostPropertyCollectionRef* p_pProps)
{
    StatusCode err = p_pProps->SetProperty(pIOPropUUID, propTypeUInt8, pMyUUID, 16);
    if (err == errNone)
    {
        const char* name = "AAC FFmpeg 6 Export Experiment";
        err = p_pProps->SetProperty(pIOPropName, propTypeString, name, strlen(name));
    }

    return err;
}

StatusCode g_HandleCreateObj(unsigned char* p_pUUID, ObjectRef* p_ppObj)
{
    if (memcmp(p_pUUID, AudioEncoder::s_UUID, 16) == 0)
    {
        *p_ppObj = new AudioEncoder();
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
    g_Log(logLevelWarn, "AAC Plugin :: g_ListCodecs");
    // For any optional/new features, please check Host version before using it
    if (GetHostAPI()->version >= 0x00000001)
    {
        return AudioEncoder::s_RegisterCodecs(p_pList);
    }

    return errNone;
}

StatusCode g_ListContainers(HostListRef* p_pList)
{
    (void)p_pList;
    g_Log(logLevelWarn, "AAC Plugin :: g_ListContainers");
    return errNone;
}

StatusCode g_GetEncoderSettings(unsigned char* p_pUUID, HostPropertyCollectionRef* p_pValues, HostListRef* p_pSettingsList)
{
    if (memcmp(p_pUUID, AudioEncoder::s_UUID, 16) == 0)
    {
        return AudioEncoder::s_GetEncoderSettings(p_pValues, p_pSettingsList);
    }

    return errNoCodec;
}
