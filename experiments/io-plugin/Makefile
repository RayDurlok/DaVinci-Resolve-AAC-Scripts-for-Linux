include .mk.defs

BASEDIR = ./

BUILD_DIR = .
SUBDIRS = wrapper
ENABLE_ENCODER ?= 0

ifeq ($(OS_TYPE), Linux)
LDFLAGS = -shared '-Wl,-rpath,$$ORIGIN' -Wl,-z,origin -lpthread
else
LDFLAGS = -dynamiclib
endif

TARGET = $(BINDIR)/aac_codec_probe_plugin.dvcp

OBJDIR = $(BUILD_DIR)/build
BINDIR = $(BUILD_DIR)/bin

.PHONY: all

HEADERS = plugin.h audio_decoder.h container_probe.h
SRCS = plugin.cpp audio_decoder.cpp container_probe.cpp wrapper/host_api.cpp
OBJS = $(SRCS:%.cpp=$(OBJDIR)/%.o)

CFLAGS += -I$(BASEDIR)/wrapper -I/usr/include/c++/14 -stdlib=libstdc++ -I/usr/include/c++/x86_64-redhat-linux/14

ifeq ($(ENABLE_ENCODER),1)
HEADERS += audio_encoder.h
SRCS += audio_encoder.cpp
LDFLAGS += $(shell pkg-config --libs libavcodec libavutil 2>/dev/null || echo -lavcodec -lavutil)
CFLAGS += -DENABLE_AAC_ENCODER=1 $(shell pkg-config --cflags libavcodec libavutil 2>/dev/null)
else
CFLAGS += -DENABLE_AAC_ENCODER=0
endif

all: prereq make-subdirs $(HEADERS) $(SRCS) $(OBJS) $(TARGET)

prereq:
	mkdir -p $(OBJDIR)
	mkdir -p $(BINDIR)
	mkdir -p $(OBJDIR)/wrapper  # Ensure wrapper directory exists

$(OBJDIR)/%.o: %.cpp
	$(CC) -c -o $@ $< $(CFLAGS)

$(OBJDIR)/wrapper/%.o: wrapper/%.cpp
	$(CC) -c -o $@ $< $(CFLAGS)

$(TARGET):
	$(CC) $(OBJDIR)/*.o $(LDFLAGS) -o $(TARGET)
#	install -Dm755 $(TARGET) /opt/resolve/IOPlugins/aac_encoder_plugin.dvcp.bundle/Contents/Linux-x86-64/aac_encoder_plugin.dvcp

clean: clean-subdirs
	rm -rf $(OBJDIR)
	rm -rf $(BINDIR)

make-subdirs:
	@for subdir in $(SUBDIRS); do \
	echo "Making $$subdir"; \
	(cd $$subdir; make; cd ..) \
	done

clean-subdirs:
	@for subdir in $(SUBDIRS); do \
	echo "Making clean in $$subdir"; \
	(cd $$subdir; make clean; cd ..) \
	done
