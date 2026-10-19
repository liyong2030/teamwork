<template>
  <div class="page-container">
    <div class="page-card">
      <div class="flex-between">
        <span class="page-title" style="margin: 0">周报详情</span>
        <el-button @click="router.back()">返回</el-button>
      </div>
    </div>

    <div class="page-card" v-if="detail">
      <el-descriptions :column="3" border size="small">
        <el-descriptions-item label="成员">{{ detail.full_name }}</el-descriptions-item>
        <el-descriptions-item label="周次">{{ detail.week_label }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="REPORT_STATUS_MAP[detail.status]?.type">{{ detail.status_label }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="提交时间">
          {{ formatDateTime(detail.submitted_at) }}
        </el-descriptions-item>
        <el-descriptions-item label="字数">{{ detail.char_count }} 字</el-descriptions-item>
        <el-descriptions-item label="有效性">
          <el-tag :type="detail.is_valid ? 'success' : 'warning'" size="small">
            {{ detail.is_valid ? '有效' : detail.invalid_reason || '待定' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="代提交人" v-if="detail.submitted_by_name">
          {{ detail.submitted_by_name }} · {{ detail.proxy_reason }}
        </el-descriptions-item>
        <el-descriptions-item label="审阅人" v-if="detail.reviewed_by_id">
          {{ formatDateTime(detail.reviewed_at) }}
        </el-descriptions-item>
      </el-descriptions>

      <el-card
        v-for="section in REPORT_SECTIONS"
        :key="section.key"
        shadow="never"
        style="margin-top: 12px"
      >
        <template #header>
          <span class="section-title">
            <el-icon :color="section.color"><component :is="section.icon" /></el-icon>
            {{ section.label }}
          </span>
        </template>
        <ol v-if="grouped[section.key]?.length" class="content-list">
          <li v-for="item in grouped[section.key]" :key="item.id">
            <span>{{ item.content }}</span>
            <el-tag v-if="item.task_id" size="small" effect="plain" style="margin-left: 8px">
              {{ item.task_title }}
            </el-tag>
          </li>
        </ol>
        <span v-else class="muted">未填写</span>
      </el-card>

      <div class="page-card" style="margin-top: 12px">
        <span class="page-title">修订历史</span>
        <el-timeline style="margin-top: 12px">
          <el-timeline-item
            v-for="rev in revisions"
            :key="rev.id"
            :timestamp="formatDateTime(rev.created_at)"
          >
            第 {{ rev.version }} 版 · {{ rev.editor_name }}
            <span v-if="rev.reason" class="muted">— {{ rev.reason }}</span>
          </el-timeline-item>
        </el-timeline>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { reportApi } from '@/api/reports'
import { REPORT_SECTIONS, REPORT_STATUS_MAP, formatDateTime } from '@/utils/dict'
import type { ReportDetail, ReportItem, ReportRevision } from '@/types'

const route = useRoute()
const router = useRouter()
const detail = ref<ReportDetail | null>(null)
const revisions = ref<ReportRevision[]>([])

const grouped = computed(() => {
  const map: Record<string, ReportItem[]> = { done: [], progress: [], risk: [], plan: [] }
  for (const item of detail.value?.items ?? []) {
    if (map[item.section]) map[item.section].push(item)
  }
  return map
})

onMounted(async () => {
  const id = Number(route.params.id)
  detail.value = await reportApi.detail(id).catch(() => null)
  revisions.value = await reportApi.revisions(id).catch(() => [])
})
</script>

<style scoped>
.section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
}

.content-list {
  margin: 0;
  padding-left: 20px;
  line-height: 1.9;
}
</style>
