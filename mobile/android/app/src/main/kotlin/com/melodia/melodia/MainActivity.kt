package com.melodia.melodia

import com.ryanheise.audioservice.AudioServiceActivity

// audio_service requires its activity so the engine is shared with the background service.
class MainActivity : AudioServiceActivity()
