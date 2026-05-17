#include <stdio.h>

#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>

int main(int argc, char **argv)
{
    if (argc != 2) {
        fprintf(stderr, "usage: %s <media-file>\n", argv[0]);
        return 2;
    }

    AVFormatContext *format = NULL;
    int ret = avformat_open_input(&format, argv[1], NULL, NULL);
    if (ret < 0) {
        char err[AV_ERROR_MAX_STRING_SIZE] = {0};
        av_strerror(ret, err, sizeof(err));
        fprintf(stderr, "avformat_open_input failed: %s\n", err);
        return 1;
    }

    ret = avformat_find_stream_info(format, NULL);
    if (ret < 0) {
        char err[AV_ERROR_MAX_STRING_SIZE] = {0};
        av_strerror(ret, err, sizeof(err));
        fprintf(stderr, "avformat_find_stream_info failed: %s\n", err);
        return 1;
    }

    int stream_index = av_find_best_stream(format, AVMEDIA_TYPE_AUDIO, -1, -1, NULL, 0);
    if (stream_index < 0) {
        fprintf(stderr, "no audio stream found\n");
        return 1;
    }

    AVStream *stream = format->streams[stream_index];
    const AVCodec *codec = avcodec_find_decoder(stream->codecpar->codec_id);
    if (!codec) {
        fprintf(stderr, "decoder not found for codec id %d\n", stream->codecpar->codec_id);
        return 1;
    }

    AVCodecContext *codec_ctx = avcodec_alloc_context3(codec);
    if (!codec_ctx) {
        fprintf(stderr, "avcodec_alloc_context3 failed\n");
        return 1;
    }

    ret = avcodec_parameters_to_context(codec_ctx, stream->codecpar);
    if (ret < 0) {
        char err[AV_ERROR_MAX_STRING_SIZE] = {0};
        av_strerror(ret, err, sizeof(err));
        fprintf(stderr, "avcodec_parameters_to_context failed: %s\n", err);
        return 1;
    }

    ret = avcodec_open2(codec_ctx, codec, NULL);
    if (ret < 0) {
        char err[AV_ERROR_MAX_STRING_SIZE] = {0};
        av_strerror(ret, err, sizeof(err));
        fprintf(stderr, "avcodec_open2 failed: %s\n", err);
        return 1;
    }

    AVPacket *packet = av_packet_alloc();
    AVFrame *frame = av_frame_alloc();
    int decoded = 0;

    while ((ret = av_read_frame(format, packet)) >= 0) {
        if (packet->stream_index == stream_index) {
            ret = avcodec_send_packet(codec_ctx, packet);
            if (ret < 0) {
                char err[AV_ERROR_MAX_STRING_SIZE] = {0};
                av_strerror(ret, err, sizeof(err));
                fprintf(stderr, "avcodec_send_packet failed: %s\n", err);
                return 1;
            }

            ret = avcodec_receive_frame(codec_ctx, frame);
            if (ret == 0) {
                printf("decoded audio: codec=%s sample_rate=%d channels=%d format=%s samples=%d\n",
                       codec->name,
                       frame->sample_rate,
                       frame->ch_layout.nb_channels,
                       av_get_sample_fmt_name(frame->format),
                       frame->nb_samples);
                decoded = 1;
                break;
            }
            if (ret != AVERROR(EAGAIN) && ret != AVERROR_EOF) {
                char err[AV_ERROR_MAX_STRING_SIZE] = {0};
                av_strerror(ret, err, sizeof(err));
                fprintf(stderr, "avcodec_receive_frame failed: %s\n", err);
                return 1;
            }
        }
        av_packet_unref(packet);
    }

    av_frame_free(&frame);
    av_packet_free(&packet);
    avcodec_free_context(&codec_ctx);
    avformat_close_input(&format);

    if (!decoded) {
        fprintf(stderr, "no audio frame decoded\n");
        return 1;
    }

    return 0;
}
