// Derived from Toxblh/davinci-linux-aac-codec (GPLv3).
// Toolkit changes: FFmpeg 6 ABI, AAC-LC metadata transport and stream draining.
#include "audio_encoder.h"

// FFMpeg includes
extern "C" {
#include <libavcodec/avcodec.h>
#include <libavutil/opt.h>
#include <libavutil/channel_layout.h>
#include <libavutil/mem.h>
#include <libavutil/error.h>
#include <libavutil/samplefmt.h>
}

#ifndef FF_PROFILE_AAC_LOW
#define FF_PROFILE_AAC_LOW 1
#endif

// NOTE: When creating a plugin for release, please generate a new Codec UUID in order to prevent conflicts with other third-party plugins.
const uint8_t AudioEncoder::s_UUID[] = { 0x71, 0xa8, 0xb9, 0x02, 0x61, 0x3d, 0x4f, 0xba, 0xa9, 0x12, 0x73, 0x24, 0x5e, 0x69, 0x0c, 0x21 };

class UIAudioSettingsController
{
public:
    UIAudioSettingsController()
    {
        InitDefaults();
    }

    ~UIAudioSettingsController()
    {
    }

    void Load(IPropertyProvider* p_pValues)
    {
        p_pValues->GetINT32("aud_enc_bitrate", m_BitRate);
    }

    StatusCode Render(HostListRef* p_pSettingsList)
    {
        HostUIConfigEntryRef item("aud_enc_bitrate");
        item.MakeSlider("Bit Rate", "kbps", m_BitRate, 128, 512, 128, 128);

        item.SetTriggersUpdate(true);
        if (!item.IsSuccess() || !p_pSettingsList->Append(&item))
        {
            g_Log(logLevelError, "Audio Plugin :: Failed to populate bitrate slider UI entry");
            return errFail;
        }

        return errNone;
    }

    int32_t GetBitRate() const
    {
        return m_BitRate;
    }

private:
    void InitDefaults()
    {
        m_BitRate = 128;
    }

private:
    int32_t m_BitRate;
};

// --- FFMpeg fields for AudioEncoder ---
struct AudioEncoderFFmpegContext {
    AVCodecContext* codecCtx = nullptr;
    AVFrame* frame = nullptr;
    AVPacket* pkt = nullptr;
    int frame_size = 0;
    int64_t pts = 0;
    int64_t inputSamples = 0;
    int64_t outputPackets = 0;
    bool drained = false;
};

static StatusCode SetAACMagicCookie(IPropertyProvider* p_pProps, const AVCodecContext* p_pCodecCtx, bool p_LogCookie = false)
{
    if (!p_pProps || !p_pCodecCtx || !p_pCodecCtx->extradata || p_pCodecCtx->extradata_size <= 0)
    {
        g_Log(logLevelWarn, "AAC Audio Plugin :: No AAC magic cookie available");
        return errNone;
    }

    StatusCode sts = p_pProps->SetProperty(
        pIOPropMagicCookie,
        propTypeUInt8,
        p_pCodecCtx->extradata,
        p_pCodecCtx->extradata_size);
    if (sts != errNone)
    {
        return sts;
    }

    uint32_t magicCookieType = 'esds';
    sts = p_pProps->SetProperty(pIOPropMagicCookieType, propTypeUInt32, &magicCookieType, 1);
    if (sts == errNone && p_LogCookie)
    {
        g_Log(logLevelWarn, "AAC Audio Plugin :: Set AAC magic cookie bytes=%d type=esds", p_pCodecCtx->extradata_size);
    }
    return sts;
}

static enum AVSampleFormat SelectAACSampleFormat(const AVCodec* p_pCodec)
{
    if (!p_pCodec || !p_pCodec->sample_fmts)
    {
        return AV_SAMPLE_FMT_FLTP;
    }

    for (const enum AVSampleFormat* pFmt = p_pCodec->sample_fmts; *pFmt != AV_SAMPLE_FMT_NONE; ++pFmt)
    {
        if (*pFmt == AV_SAMPLE_FMT_FLTP)
        {
            return *pFmt;
        }
    }

    return p_pCodec->sample_fmts[0];
}

static void LogFFmpegError(const char* p_pMessage, int p_Error)
{
    char errorBuffer[AV_ERROR_MAX_STRING_SIZE] = { 0 };
    av_strerror(p_Error, errorBuffer, sizeof(errorBuffer));
    g_Log(logLevelError, "AAC Audio Plugin :: %s: %s (%d)", p_pMessage, errorBuffer, p_Error);
}

static void SetRegisteredAACLC48000StereoCookie(HostPropertyCollectionRef* p_pProps)
{
    const uint8_t cookie[] = { 0x11, 0x90, 0x56, 0xe5, 0x00 };
    p_pProps->SetProperty(pIOPropMagicCookie, propTypeUInt8, cookie, sizeof(cookie));

    const uint32_t magicCookieType = 'esds';
    p_pProps->SetProperty(pIOPropMagicCookieType, propTypeUInt32, &magicCookieType, 1);
    g_Log(logLevelWarn, "AAC Audio Plugin :: Registered default AAC-LC 48k stereo magic cookie bytes=%zu type=esds", sizeof(cookie));
}

StatusCode AudioEncoder::s_RegisterCodecs(HostListRef* p_pList)
{
    g_Log(logLevelWarn, "AAC FFmpeg6 Experiment :: header codec=%u util=%u runtime codec=%u util=%u", LIBAVCODEC_VERSION_INT, LIBAVUTIL_VERSION_INT, avcodec_version(), avutil_version());
    if ((avcodec_version() >> 16) != LIBAVCODEC_VERSION_MAJOR ||
        (avutil_version() >> 16) != LIBAVUTIL_VERSION_MAJOR)
        return errUnsupported;
    // add audio encoder
    HostPropertyCollectionRef codecInfo;
    if (!codecInfo.IsValid())
    {
        return errAlloc;
    }

    codecInfo.SetProperty(pIOPropUUID, propTypeUInt8, AudioEncoder::s_UUID, 16);

    const char* pCodecName = "AAC-LC";
    codecInfo.SetProperty(pIOPropName, propTypeString, pCodecName, strlen(pCodecName));

    uint32_t val = 'aac ';
    codecInfo.SetProperty(pIOPropFourCC, propTypeUInt32, &val, 1);

    val = mediaAudio;
    codecInfo.SetProperty(pIOPropMediaType, propTypeUInt32, &val, 1);

    val = dirEncode;
    codecInfo.SetProperty(pIOPropCodecDirection, propTypeUInt32, &val, 1);

    // if need ieeefloat, set pIOPropIsFloat to 1 with bitdepth 32, supports only single bitdepth option of 32
    std::vector<uint32_t> bitDepths({16, 24});
    codecInfo.SetProperty(pIOPropBitDepth, propTypeUInt32, bitDepths.data(), bitDepths.size());
    codecInfo.SetProperty(pIOPropBitsPerSample, propTypeUInt32, bitDepths.data(), bitDepths.size());

    // supported sampling rates, or empty
    std::vector<uint32_t> samplingRates({48000});
    codecInfo.SetProperty(pIOPropSamplingRate, propTypeUInt32, samplingRates.data(), samplingRates.size());

    std::vector<uint32_t> channelCounts({2});
    codecInfo.SetProperty(pIOPropNumChannels, propTypeUInt32, channelCounts.data(), channelCounts.size());

    SetRegisteredAACLC48000StereoCookie(&codecInfo);

    std::vector<std::string> containerVec;

    containerVec.push_back("mp4");
    containerVec.push_back("mov");
    containerVec.push_back("mkv");
    std::string valStrings;
    for (size_t i = 0; i < containerVec.size(); ++i)
    {
        valStrings.append(containerVec[i]);
        if (i < (containerVec.size() - 1))
        {
            valStrings.append(1, '\0');
        }
    }

    codecInfo.SetProperty(pIOPropContainerList, propTypeString, valStrings.c_str(), valStrings.size());

    if (!p_pList->Append(&codecInfo))
    {
        return errFail;
    }

    return errNone;
}

StatusCode AudioEncoder::s_GetEncoderSettings(HostPropertyCollectionRef* p_pValues, HostListRef* p_pSettingsList)
{
    UIAudioSettingsController settings;
    settings.Load(p_pValues);

    return settings.Render(p_pSettingsList);
}

AudioEncoder::AudioEncoder()
{
    m_ffmpegCtx = nullptr;
}

AudioEncoder::~AudioEncoder()
{
    if (m_ffmpegCtx) {
        if (m_ffmpegCtx->frame) av_frame_free(&m_ffmpegCtx->frame);
        if (m_ffmpegCtx->pkt) av_packet_free(&m_ffmpegCtx->pkt);
        if (m_ffmpegCtx->codecCtx) avcodec_free_context(&m_ffmpegCtx->codecCtx);
        m_ffmpegCtx.reset();
    }
}

StatusCode AudioEncoder::DoInit(HostPropertyCollectionRef* p_pProps)
{
    uint32_t m_outputBitDepth = 0;
    p_pProps->GetUINT32(pIOPropBitDepth, m_outputBitDepth);
    if (m_outputBitDepth != 16 && m_outputBitDepth != 24) {
        g_Log(logLevelError, "AAC Audio Plugin :: Only 16-bit or 24-bit PCM is supported, got %d", m_outputBitDepth);
        return errFail;
    }
    uint8_t isFloat = 0;
    p_pProps->GetUINT8(pIOPropIsFloat, isFloat);
    uint32_t samplingRate = 0;
    p_pProps->GetUINT32(pIOPropSamplingRate, samplingRate);
    uint32_t numChannels = 0;
    p_pProps->GetUINT32(pIOPropNumChannels, numChannels);
    if (samplingRate != 48000 || numChannels != 2 || isFloat)
        return errUnsupported;
    uint32_t trackIdx = 0xFFFFFFFF;
    p_pProps->GetUINT32(pIOPropTrackIdx, trackIdx);
    m_pSettings.reset(new UIAudioSettingsController());
    m_pSettings->Load(p_pProps);
    int bitRate = m_pSettings->GetBitRate() * 1000;

    // --- FFMpeg AAC encoder init ---
    const AVCodec* codec = avcodec_find_encoder(AV_CODEC_ID_AAC);
    if (!codec) {
        g_Log(logLevelError, "AAC encoder not found");
        return errFail;
    }
    m_ffmpegCtx.reset(new AudioEncoderFFmpegContext());
    m_ffmpegCtx->codecCtx = avcodec_alloc_context3(codec);
    if (!m_ffmpegCtx->codecCtx) {
        g_Log(logLevelError, "Could not allocate AVCodecContext");
        return errFail;
    }
    m_ffmpegCtx->codecCtx->bit_rate = bitRate;
    m_ffmpegCtx->codecCtx->sample_fmt = SelectAACSampleFormat(codec);
    if (m_ffmpegCtx->codecCtx->sample_fmt != AV_SAMPLE_FMT_FLTP)
    {
        g_Log(logLevelError, "AAC Audio Plugin :: Unsupported AAC sample format selected: %s",
              av_get_sample_fmt_name(m_ffmpegCtx->codecCtx->sample_fmt));
        avcodec_free_context(&m_ffmpegCtx->codecCtx);
        m_ffmpegCtx.reset();
        return errFail;
    }
    m_ffmpegCtx->codecCtx->sample_rate = samplingRate;
    m_ffmpegCtx->codecCtx->time_base = AVRational{1, static_cast<int>(samplingRate)};
    m_ffmpegCtx->codecCtx->profile = FF_PROFILE_AAC_LOW;
    m_ffmpegCtx->codecCtx->flags |= AV_CODEC_FLAG_GLOBAL_HEADER;
    av_channel_layout_default(&m_ffmpegCtx->codecCtx->ch_layout, numChannels);
    m_ffmpegCtx->codecCtx->strict_std_compliance = FF_COMPLIANCE_EXPERIMENTAL;
    g_Log(logLevelWarn, "AAC Audio Plugin :: Opening AAC encoder sample_fmt=%s profile=%d global_header=%d",
          av_get_sample_fmt_name(m_ffmpegCtx->codecCtx->sample_fmt),
          m_ffmpegCtx->codecCtx->profile,
          (m_ffmpegCtx->codecCtx->flags & AV_CODEC_FLAG_GLOBAL_HEADER) ? 1 : 0);
    int openResult = avcodec_open2(m_ffmpegCtx->codecCtx, codec, nullptr);
    if (openResult < 0) {
        LogFFmpegError("Could not open AAC encoder", openResult);
        avcodec_free_context(&m_ffmpegCtx->codecCtx);
        m_ffmpegCtx.reset();
        return errFail;
    }
    m_ffmpegCtx->frame = av_frame_alloc();
    if (!m_ffmpegCtx->frame) return errAlloc;
    m_ffmpegCtx->frame->nb_samples = m_ffmpegCtx->codecCtx->frame_size;
    m_ffmpegCtx->frame->format = m_ffmpegCtx->codecCtx->sample_fmt;
    if (av_channel_layout_copy(&m_ffmpegCtx->frame->ch_layout, &m_ffmpegCtx->codecCtx->ch_layout) < 0 ||
        av_frame_get_buffer(m_ffmpegCtx->frame, 0) < 0) return errAlloc;
    m_ffmpegCtx->pkt = av_packet_alloc();
    if (!m_ffmpegCtx->pkt) return errAlloc;
    m_ffmpegCtx->frame_size = m_ffmpegCtx->codecCtx->frame_size;
    m_ffmpegCtx->pts = 0;
    g_Log(logLevelWarn, "AAC Audio Plugin :: Init Bit Depth: %d, isFloat: %d, Sampling Rate: %d, Num Channels: %d, Track Index: %d", m_outputBitDepth, isFloat, samplingRate, numChannels, trackIdx);
    // Сохраняем желаемый выходной битдпет для использования в DoProcess
    m_ffmpegCtx->frame_size = m_ffmpegCtx->codecCtx->frame_size;
    m_ffmpegCtx->pts = 0;
    m_outputBitDepth_ = m_outputBitDepth;

    // --- RINGBUFFER INIT ---
    m_channels = numChannels;
    m_frameSize = m_ffmpegCtx->frame_size;
    m_pcmRingBuffer.clear();
    m_pcmRingBuffer.resize(m_channels);
    for (size_t ch = 0; ch < m_channels; ++ch) {
        m_pcmRingBuffer[ch].resize(m_frameSize, 0.0f);
    }
    m_ringBufferFill = 0;

    StatusCode cookieStatus = SetAACMagicCookie(p_pProps, m_ffmpegCtx->codecCtx, true);
    if (cookieStatus != errNone)
    {
        g_Log(logLevelError, "AAC Audio Plugin :: Could not set AAC magic cookie during init");
        return cookieStatus;
    }

    return errNone;
}

void AudioEncoder::DoFlush()
{
    // Flush FFMpeg encoder
    if (m_ffmpegCtx && m_ffmpegCtx->codecCtx) {
        avcodec_flush_buffers(m_ffmpegCtx->codecCtx);
    }
    g_Log(logLevelWarn, "AAC Audio Plugin :: Flush");
}

StatusCode AudioEncoder::DoOpen(HostBufferRef* p_pBuff)
{
    m_pSettings.reset(new UIAudioSettingsController());
    m_pSettings->Load(p_pBuff);

    // optionally fill bitrate info hint for Resolve
    if (m_pSettings->GetBitRate() > 0)
    {
        const uint32_t bitRate = static_cast<uint32_t>(m_pSettings->GetBitRate()) * 1000;
        StatusCode sts = p_pBuff->SetProperty(pIOPropBitRate, propTypeUInt32, &bitRate, 1);
        if (sts != errNone)
        {
            return sts;
        }
    }

    uint32_t bitDepth = 0;
    p_pBuff->GetUINT32(pIOPropBitDepth, bitDepth);
    uint8_t isFloat = 0;
    p_pBuff->GetUINT8(pIOPropIsFloat, isFloat);
    uint32_t samplingRate = 0;
    p_pBuff->GetUINT32(pIOPropSamplingRate, samplingRate);
    uint32_t numChannels = 0;
    p_pBuff->GetUINT32(pIOPropNumChannels, numChannels);
    uint32_t trackIdx = 0xFFFFFFFF;
    p_pBuff->GetUINT32(pIOPropTrackIdx, trackIdx);
    g_Log(logLevelWarn, "AAC Audio Plugin :: DoOpen params: bitDepth=%u, isFloat=%u, samplingRate=%u, numChannels=%u, trackIdx=%u, bitrate=%d", bitDepth, isFloat, samplingRate, numChannels, trackIdx, m_pSettings->GetBitRate());

    StatusCode cookieStatus = SetAACMagicCookie(p_pBuff, m_ffmpegCtx ? m_ffmpegCtx->codecCtx : nullptr, true);
    if (cookieStatus != errNone)
    {
        g_Log(logLevelError, "AAC Audio Plugin :: Could not set AAC magic cookie");
        return cookieStatus;
    }

    return errNone;
}

StatusCode AudioEncoder::DoProcess(HostBufferRef* p_pBuff)
{
    if (!m_ffmpegCtx || !m_ffmpegCtx->codecCtx) return errFail;
    // The SDK wraps the null end-of-stream handle in a non-null C++ object.
    if (p_pBuff && !p_pBuff->IsValid()) p_pBuff = nullptr;
    if (m_ffmpegCtx->drained) return p_pBuff ? errInvalidOperation : errNone;
    uint32_t inputBitDepth = 0;
    if (p_pBuff && !p_pBuff->GetUINT32(pIOPropBitDepth, inputBitDepth)) {
        inputBitDepth = m_outputBitDepth_;
    }
    if (inputBitDepth != 16 && inputBitDepth != 24) {
        inputBitDepth = m_outputBitDepth_;
    }
    int numChannels = m_channels;
    int frame_size = m_frameSize;
    auto emitPacket = [this]() -> StatusCode {
        HostBufferRef outBuf;
        // Resolve 21's plugin cookie getter returns no codec configuration.
        // ADTS lets the MP4 muxer's aac_adtstoasc filter recover the ASC.
        const size_t packetSize = m_ffmpegCtx->pkt->size + 7;
        if (packetSize > 8191 || !outBuf.Resize(packetSize)) return errFail;
        char* outData = nullptr;
        size_t outSize = 0;
        if (!outBuf.LockBuffer(&outData, &outSize)) return errFail;
        if (outSize < packetSize)
        {
            outBuf.UnlockBuffer();
            return errFail;
        }
        const uint8_t adts[7] = {
            0xff, 0xf1, 0x4c,
            static_cast<uint8_t>(0x80 | (packetSize >> 11)),
            static_cast<uint8_t>(packetSize >> 3),
            static_cast<uint8_t>(((packetSize & 7) << 5) | 0x1f), 0xfc
        };
        memcpy(outData, adts, sizeof(adts));
        memcpy(outData + sizeof(adts), m_ffmpegCtx->pkt->data, m_ffmpegCtx->pkt->size);
        outBuf.UnlockBuffer();

        outBuf.SetProperty(pIOPropBitDepth, propTypeUInt32, &m_outputBitDepth_, 1);
        outBuf.SetProperty(pIOPropSamplingRate, propTypeUInt32, &m_ffmpegCtx->codecCtx->sample_rate, 1);
        uint32_t numChannels_ = m_ffmpegCtx->codecCtx->ch_layout.nb_channels;
        outBuf.SetProperty(pIOPropNumChannels, propTypeUInt32, &numChannels_, 1);
        uint8_t isKey = 1;
        outBuf.SetProperty(pIOPropIsKeyFrame, propTypeUInt8, &isKey, 1);
        int64_t pkt_pts = m_ffmpegCtx->pkt->pts;
        outBuf.SetProperty(pIOPropPTS, propTypeInt64, &pkt_pts, 1);
        int64_t pkt_dur = m_ffmpegCtx->pkt->duration;
        outBuf.SetProperty(pIOPropDuration, propTypeInt64, &pkt_dur, 1);
        SetAACMagicCookie(&outBuf, m_ffmpegCtx->codecCtx);
        const StatusCode status = IPluginCodecRef::DoProcess(&outBuf);
        if (status != errNone)
            g_Log(logLevelError, "AAC FFmpeg6 Experiment :: output callback failed status=%d packet=%lld", status, static_cast<long long>(m_ffmpegCtx->outputPackets));
        else
            ++m_ffmpegCtx->outputPackets;
        return status;
    };

    if (p_pBuff != NULL)
    {
        char* pBuf = NULL;
        size_t bufSize = 0;
        if (!p_pBuff->LockBuffer(&pBuf, &bufSize)) return errFail;
        if (bufSize == 0)
        {
            p_pBuff->UnlockBuffer();
            return DoProcess(nullptr);
        }
        int bytesPerSample = (inputBitDepth == 16) ? 2 : 3;
        if (bufSize % (numChannels * bytesPerSample)) {
            p_pBuff->UnlockBuffer();
            return errFail;
        }
        int totalSamples = bufSize / (numChannels * bytesPerSample);
        m_ffmpegCtx->inputSamples += totalSamples;
        std::vector<std::vector<float>> planarPCM(numChannels, std::vector<float>(totalSamples, 0.0f));
        if (inputBitDepth == 16) {
            int16_t* src = (int16_t*)pBuf;
            for (int i = 0; i < totalSamples; ++i) {
                for (int ch = 0; ch < numChannels; ++ch) {
                    planarPCM[ch][i] = src[i * numChannels + ch] / 32768.0f;
                }
            }
        } else if (inputBitDepth == 24) {
            unsigned char* src = (unsigned char*)pBuf;
            for (int i = 0; i < totalSamples; ++i) {
                for (int ch = 0; ch < numChannels; ++ch) {
                    int idx = (i * numChannels + ch) * 3;
                    int32_t sample = src[idx] | (src[idx + 1] << 8) | (src[idx + 2] << 16);
                    if (sample & 0x800000) sample -= 0x1000000;
                    planarPCM[ch][i] = sample / 8388608.0f;
                }
            }
        }
        p_pBuff->UnlockBuffer();
        int sampleIdx = 0;
        while (sampleIdx < totalSamples) {
            int chunk = std::min((int)(frame_size - m_ringBufferFill), totalSamples - sampleIdx);
            std::vector<const float*> chunkPtrs(numChannels);
            for (int ch = 0; ch < numChannels; ++ch) {
                chunkPtrs[ch] = &planarPCM[ch][sampleIdx];
            }
            AddPCMToRingBuffer(chunkPtrs.data(), chunk);
            if (IsRingBufferFull()) {
                AVFrame* tempFrame = av_frame_alloc();
                if (!tempFrame) return errAlloc;
                tempFrame->format = m_ffmpegCtx->codecCtx->sample_fmt;
                tempFrame->nb_samples = frame_size;
                if (av_channel_layout_copy(&tempFrame->ch_layout, &m_ffmpegCtx->codecCtx->ch_layout) < 0 ||
                    av_frame_get_buffer(tempFrame, 0) < 0) {
                    av_frame_free(&tempFrame);
                    return errAlloc;
                }
                float** dst = (float**)tempFrame->extended_data;
                GetFrameFromRingBuffer(dst, frame_size);
                tempFrame->pts = m_ffmpegCtx->pts;
                m_ffmpegCtx->pts += frame_size;
                int ret = avcodec_send_frame(m_ffmpegCtx->codecCtx, tempFrame);
                av_frame_free(&tempFrame);
                if (ret < 0) {
                    LogFFmpegError("send audio frame", ret);
                    return errFail;
                }
                do {
                    ret = avcodec_receive_packet(m_ffmpegCtx->codecCtx, m_ffmpegCtx->pkt);
                    if (ret == AVERROR(EAGAIN) || ret == AVERROR_EOF)
                        break;
                    else if (ret < 0) {
                        LogFFmpegError("receive audio packet", ret);
                        return errFail;
                    }
                    if (emitPacket() != errNone)
                    {
                        return errFail;
                    }
                    av_packet_unref(m_ffmpegCtx->pkt);
                } while (ret >= 0);
                ResetRingBuffer();
            }
            sampleIdx += chunk;
        }
    } else {
        g_Log(logLevelWarn, "AAC FFmpeg6 Experiment :: draining samples=%lld packets=%lld pending=%zu", static_cast<long long>(m_ffmpegCtx->inputSamples), static_cast<long long>(m_ffmpegCtx->outputPackets), m_ringBufferFill);
        if (m_ringBufferFill > 0) {
            PadAndFlushRingBuffer();
            AVFrame* tempFrame = av_frame_alloc();
            if (!tempFrame) return errAlloc;
            tempFrame->format = m_ffmpegCtx->codecCtx->sample_fmt;
            tempFrame->nb_samples = frame_size;
            if (av_channel_layout_copy(&tempFrame->ch_layout, &m_ffmpegCtx->codecCtx->ch_layout) < 0 ||
                av_frame_get_buffer(tempFrame, 0) < 0) {
                av_frame_free(&tempFrame);
                return errAlloc;
            }
            float** dst = (float**)tempFrame->extended_data;
            GetFrameFromRingBuffer(dst, frame_size);
            tempFrame->pts = m_ffmpegCtx->pts;
            m_ffmpegCtx->pts += frame_size;
            int ret = avcodec_send_frame(m_ffmpegCtx->codecCtx, tempFrame);
            av_frame_free(&tempFrame);
            if (ret < 0) {
                LogFFmpegError("send final partial frame", ret);
                return errFail;
            }
            do {
                ret = avcodec_receive_packet(m_ffmpegCtx->codecCtx, m_ffmpegCtx->pkt);
                if (ret == AVERROR(EAGAIN) || ret == AVERROR_EOF)
                    break;
                else if (ret < 0) {
                    LogFFmpegError("receive final partial packet", ret);
                    return errFail;
                }
                if (emitPacket() != errNone)
                {
                    return errFail;
                }
                av_packet_unref(m_ffmpegCtx->pkt);
            } while (ret >= 0);
            ResetRingBuffer();
        }
        // --- FLUSH ---
        int ret = avcodec_send_frame(m_ffmpegCtx->codecCtx, nullptr);
        if (ret < 0 && ret != AVERROR_EOF) {
            LogFFmpegError("send end of stream", ret);
            return errFail;
        }
        do {
            ret = avcodec_receive_packet(m_ffmpegCtx->codecCtx, m_ffmpegCtx->pkt);
            if (ret == AVERROR(EAGAIN) || ret == AVERROR_EOF)
                break;
            else if (ret < 0) {
                LogFFmpegError("drain final packets", ret);
                return errFail;
            }
            if (emitPacket() != errNone)
            {
                return errFail;
            }
            av_packet_unref(m_ffmpegCtx->pkt);
        } while (ret >= 0);
        m_ffmpegCtx->drained = true;
        g_Log(logLevelWarn, "AAC FFmpeg6 Experiment :: drain complete packets=%lld", static_cast<long long>(m_ffmpegCtx->outputPackets));
    }
    return errNone;
}

// --- RINGBUFFER HELPERS ---
void AudioEncoder::AddPCMToRingBuffer(const float** planarPCM, size_t samples) {
    for (size_t i = 0; i < samples; ++i) {
        for (size_t ch = 0; ch < m_channels; ++ch) {
            if (m_ringBufferFill < m_frameSize)
                m_pcmRingBuffer[ch][m_ringBufferFill] = planarPCM[ch][i];
        }
        m_ringBufferFill++;
    }
}

bool AudioEncoder::IsRingBufferFull() const {
    return m_ringBufferFill >= m_frameSize;
}

void AudioEncoder::GetFrameFromRingBuffer(float** out, size_t samples) {
    for (size_t ch = 0; ch < m_channels; ++ch) {
        memcpy(out[ch], m_pcmRingBuffer[ch].data(), samples * sizeof(float));
    }
}

void AudioEncoder::PadAndFlushRingBuffer() {
    if (m_ringBufferFill == 0) return;
    for (size_t ch = 0; ch < m_channels; ++ch) {
        for (size_t i = m_ringBufferFill; i < m_frameSize; ++i) {
            m_pcmRingBuffer[ch][i] = 0.0f;
        }
    }
}

void AudioEncoder::ResetRingBuffer() {
    m_ringBufferFill = 0;
    for (size_t ch = 0; ch < m_channels; ++ch) {
        std::fill(m_pcmRingBuffer[ch].begin(), m_pcmRingBuffer[ch].end(), 0.0f);
    }
}
