/**
 * 接口层入口：自动切换两种运行模式
 *  - 纯前端模式（VITE_STANDALONE=1）：数据存浏览器，AI 由浏览器直连，双击网页即可用
 *  - 后端模式（默认）：数据存磁盘，接口走 FastAPI
 */
import * as backendApi from './backend'
import * as localApi from './standalone'

export const isStandalone = import.meta.env.VITE_STANDALONE === '1'
const impl = isStandalone ? localApi : backendApi

export const listTrees = (...a) => impl.listTrees(...a)
export const createTree = (...a) => impl.createTree(...a)
export const getTree = (...a) => impl.getTree(...a)
export const createChildNode = (...a) => impl.createChildNode(...a)
export const updateNodeApi = (...a) => impl.updateNodeApi(...a)
export const deleteNodeApi = (...a) => impl.deleteNodeApi(...a)
export const deleteTreeApi = (...a) => impl.deleteTreeApi(...a)
export const renameTreeApi = (...a) => impl.renameTreeApi(...a)
export const duplicateNode = (...a) => impl.duplicateNode(...a)
export const saveTreeSnapshot = (...a) => impl.saveTreeSnapshot(...a)
export const exportTree = (...a) => impl.exportTree(...a)
export const getLlmConfig = (...a) => impl.getLlmConfig(...a)
export const updateLlmConfig = (...a) => impl.updateLlmConfig(...a)
export const saveLlmProfile = (...a) => impl.saveLlmProfile(...a)
export const deleteLlmProfile = (...a) => impl.deleteLlmProfile(...a)
export const activateLlmProfile = (...a) => impl.activateLlmProfile(...a)
export const testLlm = (...a) => impl.testLlm(...a)
export const sendQuestionStream = (...a) => impl.sendQuestionStream(...a)
