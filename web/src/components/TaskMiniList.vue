<template>
  <div class="mini-list">
    <el-empty v-if="!tasks.length" description="无" :image-size="44" />
    <div v-for="task in tasks" :key="task.id" class="mini-item">
      <div class="mini-head">
        <el-tag size="small" :type="TASK_PRIORITY_MAP[task.priority]?.type">
          {{ task.priority }}
        </el-tag>
        <span class="mini-title" :title="task.title" @click="emit('open', task)">
          {{ task.title }}
        </span>
      </div>
      <div class="mini-meta">
        <span>{{ task.project_name }}</span>
        <el-progress
          :percentage="task.progress"
          :stroke-width="5"
          :show-text="false"
          style="width: 60px"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { TASK_PRIORITY_MAP } from '@/utils/dict'
import type { TaskItem } from '@/types'

defineProps<{ tasks: TaskItem[] }>()
const emit = defineEmits<{ (e: 'open', task: TaskItem): void }>()
</script>

<style scoped>
.mini-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.mini-head {
  display: flex;
  align-items: center;
  gap: 6px;
}

.mini-title {
  font-size: 13px;
  color: #1f2937;
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mini-title:hover {
  color: var(--ctms-primary);
}

.mini-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 4px;
  font-size: 12px;
  color: #6b7280;
}
</style>
