# Android installer storage

CI stages the signed APK in this directory before uploading it. Published APKs
live permanently in the matching versioned GitHub Release; they are not
committed to Git because they exceed normal repository file-size limits.
