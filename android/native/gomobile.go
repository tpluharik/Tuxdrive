// Package gomobile exposes the rclone RPC surface required by TuxInDrive.
package gomobile

import (
    "github.com/rclone/rclone/librclone/librclone"

    _ "github.com/rclone/rclone/backend/all"
    _ "github.com/rclone/rclone/cmd/bisync"
    _ "github.com/rclone/rclone/fs/operations"
    _ "github.com/rclone/rclone/fs/sync"
)

type RcloneRPCResult struct {
    Output string
    Status int
}

func RcloneInitialize() {
    librclone.Initialize()
}

func RcloneFinalize() {
    librclone.Finalize()
}

func RcloneRPC(method string, input string) *RcloneRPCResult {
    output, status := librclone.RPC(method, input)
    return &RcloneRPCResult{Output: output, Status: status}
}
