import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, Input, Button } from '@tarojs/components';
import Taro from '@tarojs/taro';
import classnames from 'classnames';
import StateView from '@/components/StateView';
import DisclaimerBar from '@/components/DisclaimerBar';
import { fetchDiseases, fetchDrugs, searchDiseases } from '@/services/patientService';
import { KNOWLEDGE_TABS, MOCK_NOTICE } from '@/utils/constants';
import type { DiseaseCard, DrugItem } from '@/types/api';
import styles from './index.module.scss';

type TabKey = 'disease' | 'drug';

const KnowledgePage: React.FC = () => {
  const [tab, setTab] = useState<TabKey>('disease');
  const [keyword, setKeyword] = useState('');
  const [diseases, setDiseases] = useState<DiseaseCard[]>([]);
  const [drugs, setDrugs] = useState<DrugItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [fromMock, setFromMock] = useState(false);

  const load = useCallback(
    async (which: TabKey, kw: string) => {
      setLoading(true);
      try {
        if (which === 'disease') {
          const res = kw ? await searchDiseases(kw, 'name') : await fetchDiseases({});
          setDiseases(res.data.items);
          setFromMock(res.fromMock);
        } else {
          const res = await fetchDrugs(kw);
          setDrugs(res.data.items);
          setFromMock(res.fromMock);
        }
      } catch (e) {
        console.error('[Knowledge] 加载失败:', e);
        setFromMock(true);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  useEffect(() => {
    load('disease', '');
    // 仅首次挂载时加载；后续由切页签 / 搜索主动触发
  }, [load]);

  const switchTab = (next: TabKey) => {
    if (next === tab) {
      return;
    }
    setTab(next);
    setKeyword('');
    load(next, '');
  };

  const handleSearch = () => {
    load(tab, keyword.trim());
  };

  const openDisease = (id: string) => {
    Taro.navigateTo({ url: `/pages/disease-detail/index?id=${encodeURIComponent(id)}` });
  };

  const openDrug = (id: string) => {
    Taro.navigateTo({ url: `/pages/drug-detail/index?id=${encodeURIComponent(id)}` });
  };

  const isEmpty = tab === 'disease' ? diseases.length === 0 : drugs.length === 0;

  return (
    <View className={styles.page}>
      <View className={styles.tabs}>
        {KNOWLEDGE_TABS.map((t) => (
          <View
            key={t.key}
            className={classnames(styles.tab, tab === t.key && styles.tabActive)}
            onClick={() => switchTab(t.key as TabKey)}
          >
            <Text className={classnames(styles.tabText, tab === t.key && styles.tabTextActive)}>{t.label}</Text>
          </View>
        ))}
      </View>

      <View className={styles.searchBar}>
        <Input
          className={styles.searchInput}
          value={keyword}
          placeholder={tab === 'disease' ? '搜索疾病名称' : '搜索药品名称'}
          confirmType="search"
          onInput={(e) => setKeyword(e.detail.value)}
          onConfirm={handleSearch}
        />
        <Button className={styles.searchBtn} onClick={handleSearch}>
          搜索
        </Button>
      </View>

      {fromMock && !loading && <Text className={styles.mockNotice}>{MOCK_NOTICE}</Text>}

      {loading ? (
        <StateView type="loading" />
      ) : isEmpty ? (
        <StateView type="empty" text="未找到相关内容，可换个关键词试试" />
      ) : (
        <View className={styles.list}>
          {tab === 'disease'
            ? diseases.map((d) => (
                <View key={d.disease_id} className={styles.item} onClick={() => openDisease(d.disease_id)}>
                  <View className={styles.itemHead}>
                    <Text className={styles.itemTitle}>{d.name_canonical}</Text>
                    {d.category_label ? <Text className={styles.itemTag}>{d.category_label}</Text> : null}
                    <Text className={styles.itemArrow}>›</Text>
                  </View>
                  <Text className={styles.itemDesc}>{d.overview}</Text>
                </View>
              ))
            : drugs.map((d) => (
                <View key={d.drug_id} className={styles.item} onClick={() => openDrug(d.drug_id)}>
                  <View className={styles.itemHead}>
                    <Text className={styles.itemTitle}>{d.generic_name}</Text>
                    <Text className={styles.itemArrow}>›</Text>
                  </View>
                  {d.aliases_zh && d.aliases_zh.length > 0 ? (
                    <Text className={styles.itemAlias}>{d.aliases_zh.join('、')}</Text>
                  ) : null}
                  {d.brand_names && d.brand_names.length > 0 ? (
                    <Text className={styles.itemDesc}>商品名：{d.brand_names.join('、')}</Text>
                  ) : null}
                </View>
              ))}
        </View>
      )}

      <DisclaimerBar />
    </View>
  );
};

export default KnowledgePage;
