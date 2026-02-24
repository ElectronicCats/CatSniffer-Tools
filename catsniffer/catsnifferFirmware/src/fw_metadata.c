#include "fw_metadata.h"

#include <errno.h>
#include <string.h>
#include <zephyr/fs/nvs.h>
#include <zephyr/storage/flash_map.h>
#include <zephyr/sys/util.h>

static const char *const official_fw_ids[] = {
	"sniffle",
	"ti_sniffer",
	"catsniffer_v3",
	"airtag_spoofer_cc1352p7",
	"airtag_scanner_cc1352p7",
};

static struct nvs_fs fs;
static char stored_cc1352_fw_id[CC1352_FW_ID_MAX_LEN];
static int has_fw_id;
static int initialized;
static int storage_unavailable;

#define FW_META_NVS_ID_CC1352_FW_ID 1
#define FW_META_STORAGE_SECTOR_COUNT 2

static int fw_metadata_validate_id(const char *fw_id)
{
	size_t len;

	if (fw_id == NULL) {
		return -EINVAL;
	}

	len = strlen(fw_id);
	if (len == 0 || len >= CC1352_FW_ID_MAX_LEN) {
		return -EINVAL;
	}

	for (size_t i = 0; i < len; i++) {
		char c = fw_id[i];
		int is_alnum = (c >= '0' && c <= '9') ||
			       (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z');
		if (!is_alnum && c != '_' && c != '-' && c != '.') {
			return -EINVAL;
		}
	}

	return 0;
}

int fw_metadata_init(void)
{
	const struct flash_area *fa;
	char tmp[CC1352_FW_ID_MAX_LEN];
	ssize_t len;
	int rc;

	if (initialized) {
		return 0;
	}

	rc = flash_area_open(FIXED_PARTITION_ID(storage_partition), &fa);
	if (rc < 0) {
		storage_unavailable = 1;
		return rc;
	}

	fs.flash_device = fa->fa_dev;
	fs.offset = fa->fa_off;
	fs.sector_size = fa->fa_size / FW_META_STORAGE_SECTOR_COUNT;
	fs.sector_count = FW_META_STORAGE_SECTOR_COUNT;

	rc = nvs_mount(&fs);
	flash_area_close(fa);
	if (rc < 0) {
		storage_unavailable = 1;
		return rc;
	}

	memset(stored_cc1352_fw_id, 0, sizeof(stored_cc1352_fw_id));
	has_fw_id = 0;

	len = nvs_read(&fs, FW_META_NVS_ID_CC1352_FW_ID, tmp, sizeof(tmp) - 1);
	if (len > 0) {
		tmp[len] = '\0';
		if (fw_metadata_validate_id(tmp) == 0) {
			strncpy(stored_cc1352_fw_id, tmp,
				sizeof(stored_cc1352_fw_id) - 1);
			has_fw_id = 1;
		}
	}

	initialized = 1;
	return 0;
}

int fw_metadata_set_cc1352_fw_id(const char *fw_id)
{
	int rc;

	rc = fw_metadata_validate_id(fw_id);
	if (rc < 0) {
		return rc;
	}

	if (!initialized) {
		rc = fw_metadata_init();
		if (rc < 0) {
			return rc;
		}
	}

	rc = nvs_write(&fs, FW_META_NVS_ID_CC1352_FW_ID, fw_id, strlen(fw_id));
	if (rc < 0) {
		return rc;
	}

	memset(stored_cc1352_fw_id, 0, sizeof(stored_cc1352_fw_id));
	strncpy(stored_cc1352_fw_id, fw_id, sizeof(stored_cc1352_fw_id) - 1);
	has_fw_id = 1;
	return 0;
}

int fw_metadata_get_cc1352_fw_id(char *buf, size_t buf_len)
{
	if (!initialized) {
		int rc = fw_metadata_init();
		if (rc < 0) {
			return rc;
		}
	}

	if (!has_fw_id) {
		return -ENOENT;
	}

	if (buf == NULL || buf_len == 0) {
		return -EINVAL;
	}

	strncpy(buf, stored_cc1352_fw_id, buf_len - 1);
	buf[buf_len - 1] = '\0';
	return 0;
}

int fw_metadata_clear_cc1352_fw_id(void)
{
	int rc;

	if (!initialized) {
		rc = fw_metadata_init();
		if (rc < 0) {
			return rc;
		}
	}

	rc = nvs_delete(&fs, FW_META_NVS_ID_CC1352_FW_ID);
	if (rc < 0) {
		return rc;
	}

	memset(stored_cc1352_fw_id, 0, sizeof(stored_cc1352_fw_id));
	has_fw_id = 0;
	return 0;
}

int fw_metadata_has_cc1352_fw_id(void)
{
	if (!initialized && !storage_unavailable) {
		(void)fw_metadata_init();
	}
	return has_fw_id;
}

int fw_metadata_is_official_cc1352_fw_id(const char *fw_id)
{
	for (size_t i = 0; i < ARRAY_SIZE(official_fw_ids); i++) {
		if (strcmp(fw_id, official_fw_ids[i]) == 0) {
			return 1;
		}
	}
	return 0;
}

const char *fw_metadata_official_id_by_index(size_t index)
{
	if (index >= ARRAY_SIZE(official_fw_ids)) {
		return NULL;
	}
	return official_fw_ids[index];
}

size_t fw_metadata_official_id_count(void)
{
	return ARRAY_SIZE(official_fw_ids);
}
