<template>
  <div class="page-container">
    <div class="page-card">
      <div class="flex-between">
        <span class="page-title" style="margin: 0">消息中心</span>
        <div>
          <el-switch
            v-model="onlyUnread"
            active-text="仅未读"
            @change="loadList"
            style="margin-right: 10px"
          />
          <el-button @click="loadList"><el-icon><Refresh /></el-icon></el-button>
        </div>
      </div>
      <el-empty v-if="!list.length" description="暂无消息" />
      <div v-else class="notice-list">
        <div
          v-for="item in list"
          :key="item.id"
          class="notice-item"
          :class="{ 'is-read': item.is_read }"
          @click="read(item)"
        >
          <div class="notice-head">
            <el-icon :color="item.is_read ? '#9ca3af' : '#2f5597'"><Bell /></el-icon>
            <span class="notice-title">{{ item.title }}</span>
            <el-tag v-if="!item.is_read" size="small" type="danger">未读</el-tag>
          </div>
          <div class="notice-content">{{ item.content }}</div>
          <div class="notice-foot muted">{{ formatDateTime(item.created_at) }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { systemApi } from '@/api/system'
import { formatDateTime } from '@/utils/dict'
import type { NotificationItem } from '@/types'

const list = ref<NotificationItem[]>([])
const onlyUnread = ref(false)

async function loadList() {
  list.value = await systemApi
    .notifications({ unread_only: onlyUnread.value, limit: 100 })
    .catch(() => [])
}

async function read(item: NotificationItem) {
  if (!item.is_read) {
    await systemApi.markRead(item.id).catch(() => null)
    await loadList()
  }
}

onMounted(loadList)
</script>

<style scoped>
.notice-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 12px;
}

.notice-item {
  border: 1px solid #eef2f7;
  border-left: 3px solid var(--ctms-primary);
  border-radius: 6px;
  padding: 12px;
  cursor: pointer;
}

.notice-item.is-read {
  border-left-color: #d1d5db;
  background: #fafbfc;
}

.notice-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.notice-title {
  font-weight: 600;
  font-size: 14px;
}

.notice-content {
  margin: 6px 0 4px;
  color: #374151;
  line-height: 1.7;
}
</style>
