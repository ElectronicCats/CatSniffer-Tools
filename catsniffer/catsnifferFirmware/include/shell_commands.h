/*
 * shell_commands.h - Shell Command Parser Interface
 */

#ifndef SHELL_COMMANDS_H
#define SHELL_COMMANDS_H

#include <stddef.h>

// Parse and execute a command line (null-terminated string)
void process_command(char *cmd, size_t len);

#endif
