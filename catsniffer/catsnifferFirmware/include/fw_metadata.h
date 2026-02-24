#ifndef FW_METADATA_H
#define FW_METADATA_H

#include <stddef.h>

#define CC1352_FW_ID_MAX_LEN 32

int fw_metadata_init(void);
int fw_metadata_set_cc1352_fw_id(const char *fw_id);
int fw_metadata_get_cc1352_fw_id(char *buf, size_t buf_len);
int fw_metadata_clear_cc1352_fw_id(void);
int fw_metadata_has_cc1352_fw_id(void);
int fw_metadata_is_official_cc1352_fw_id(const char *fw_id);
const char *fw_metadata_official_id_by_index(size_t index);
size_t fw_metadata_official_id_count(void);

#endif /* FW_METADATA_H */
